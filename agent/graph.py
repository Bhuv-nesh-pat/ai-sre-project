"""
LangGraph State Machine for the AI SRE Agent.
"""
import sys
import os
from typing import Annotated, TypedDict, Optional, Any, Literal
from pydantic import BaseModel, Field
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

# Add parent directory to path to import agent modules correctly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.prompts import ZERO_TRUST_SYSTEM_PROMPT
from agent.tools.k8s_tools import read_only_tools, mutating_tools, restart_pod
from agent.tools.prom_tools import prom_tools

# Define the State Schema (TypedDict) with message reducers
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    observability_context: dict[str, Any]
    localized_entity: Optional[str]
    fault_identification: Optional[str]
    proposed_remediation: Optional[str]
    step_count: int
    remediation_attempts: int

# Define the Remediation Payload Schema (Contract 3)
class RemediationPayload(BaseModel):
    localized_entity: str = Field(description="The specific pod or service affected")
    fault_identification: str = Field(description="The nature of the anomaly")
    remediation_plan: str = Field(description="The proposed remediation action")

# Initialize LLM and bind actual tools
# Note: Ensure GOOGLE_API_KEY is set in your environment
try:
    llm = ChatGoogleGenerativeAI(model="gemini-3.1-pro-preview", temperature=0)
    all_tools = read_only_tools + prom_tools
    llm_with_tools = llm.bind_tools(all_tools + [RemediationPayload])
except Exception as e:
    print(f"Warning: Failed to initialize LLM. Ensure GOOGLE_API_KEY is set. Error: {e}")
    llm_with_tools = None

def planner_node(state: AgentState) -> dict:
    """Planner node for diagnostic reasoning."""
    step_count = state.get("step_count", 0) + 1
    remediation_attempts = state.get("remediation_attempts", 0)
    
    # Software Circuit Breaker
    if step_count > 15:
        return {
            "messages": [AIMessage(content="Circuit breaker tripped: Maximum step count (15) exceeded. Gracefully degrading and halting diagnostic process.")],
            "step_count": step_count
        }
    
    if remediation_attempts >= 1:
        return {
             "messages": [AIMessage(content="Circuit breaker tripped: Maximum remediation attempts (1) reached. Halting action to prevent cascading failures.")],
             "step_count": step_count
        }

    messages = state.get("messages", [])
    
    # Prepend the Zero Trust system prompt on the first inference step
    if step_count == 1:
        messages = [{"role": "system", "content": ZERO_TRUST_SYSTEM_PROMPT}] + messages

    response = llm_with_tools.invoke(messages)
    
    # Determine if the LLM outputted the RemediationPayload structure via a tool call
    localized_entity = state.get("localized_entity")
    fault_identification = state.get("fault_identification")
    proposed_remediation = state.get("proposed_remediation")
    
    if hasattr(response, 'tool_calls') and response.tool_calls:
        for tool_call in response.tool_calls:
            if tool_call["name"] == "RemediationPayload":
                args = tool_call["args"]
                localized_entity = args.get("localized_entity")
                fault_identification = args.get("fault_identification")
                proposed_remediation = args.get("remediation_plan")
    
    return {
        "messages": [response],
        "step_count": step_count,
        "localized_entity": localized_entity,
        "fault_identification": fault_identification,
        "proposed_remediation": proposed_remediation
    }

def tool_execution_node(state: AgentState) -> dict:
    """Executes read-only observability tools."""
    messages = state.get("messages", [])
    last_message = messages[-1]
    
    tool_responses = []
    tool_map = {t.name: t for t in all_tools}
    
    for tool_call in getattr(last_message, 'tool_calls', []):
        if tool_call["name"] == "RemediationPayload":
            continue # Skipped here, handled by routing logic to authorization_node
            
        tool_instance = tool_map.get(tool_call["name"])
        if tool_instance:
            try:
                result = tool_instance.invoke(tool_call["args"])
            except Exception as e:
                result = f"Error executing {tool_call['name']}: {str(e)}"
                
            tool_responses.append(
                ToolMessage(content=str(result), name=tool_call["name"], tool_call_id=tool_call["id"])
            )
            
    return {"messages": tool_responses}

def authorization_node(state: AgentState) -> Command[Literal["mutating_tool_node", "planner_node"]]:
    """Human-in-the-loop authorization node."""
    # Ensure the payload perfectly matches the JSON dictionary defined in Contract 3
    payload = {
        "localized_entity": state.get("localized_entity", "unknown"),
        "fault_identification": state.get("fault_identification", "unknown"),
        "remediation_plan": state.get("proposed_remediation", "unknown")
    }
    
    # Immediately suspends the graph's execution, surfacing the payload
    # Resumption requires Command(resume="approve") or Command(resume="reject")
    human_decision = interrupt(payload)
    
    if human_decision == "approve":
        return Command(
            goto="mutating_tool_node", 
            update={"remediation_attempts": state.get("remediation_attempts", 0) + 1}
        )
    else: # reject
        return Command(
            goto="planner_node", 
            update={
                "messages": [HumanMessage(content="Remediation rejected by human operator. Re-evaluate evidence.")],
                "proposed_remediation": None # Clear to prevent immediate re-triggering
            }
        )

def mutating_tool_node(state: AgentState) -> dict:
    """Executes state-altering commands after human approval."""
    entity = state.get("localized_entity", "")
    
    try:
         # Trigger the real kubernetes mutating tool
         result = restart_pod.invoke({"pod_name": entity})
    except Exception as e:
         result = f"Failed to execute remediation: {e}"
         
    return {"messages": [AIMessage(content=f"Remediation executed. Result: {result}")]}

def routing_logic(state: AgentState) -> str:
    """Controls the ReAct loop between reasoning, tool execution, and authorization."""
    messages = state.get("messages", [])
    if not messages:
         return "planner_node"
    
    last_message = messages[-1]
    
    if hasattr(last_message, "content") and "Circuit breaker tripped" in last_message.content:
        return END
        
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        # Check if the LLM generated the RemediationPayload structure to request approval
        for tool_call in last_message.tool_calls:
            if tool_call["name"] == "RemediationPayload":
                 return "authorization_node"
        
        # Otherwise, route to execute the standard observability tools
        return "tool_execution_node"
        
    return END

# Construct the StateGraph
workflow = StateGraph(AgentState)

workflow.add_node("planner_node", planner_node)
workflow.add_node("tool_execution_node", tool_execution_node)
workflow.add_node("authorization_node", authorization_node)
workflow.add_node("mutating_tool_node", mutating_tool_node)

workflow.add_edge(START, "planner_node")
workflow.add_conditional_edges(
    "planner_node",
    routing_logic,
    {
        "tool_execution_node": "tool_execution_node",
        "authorization_node": "authorization_node",
        END: END
    }
)
workflow.add_edge("tool_execution_node", "planner_node")
workflow.add_edge("mutating_tool_node", END)

# Instantiate InMemorySaver for local development and checkpointing
checkpointer = InMemorySaver()
app = workflow.compile(checkpointer=checkpointer)
