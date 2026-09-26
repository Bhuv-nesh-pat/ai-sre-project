import uuid
from langchain_core.messages import HumanMessage
from agent.graph import app 

print("--- AI SRE Agent Interactive CLI ---")
print("Paste the alert or problem description below. Type 'exit' to quit.\n")

while True:
    user_prompt = input("Problem/Alert: ")
    if user_prompt.lower() == "exit":
        break
        
    print("\n[Agent is investigating...]\n")
    
    # Generate a fresh thread_id for every alert so memory is clean
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    
    # Run the agent
    result = app.invoke({"messages": [HumanMessage(content=user_prompt)]}, config=config)
    
    print("=== Investigation Log ===")
    for msg in result["messages"]:
        # Print the AI's conversational reasoning
        if msg.type == "ai" and msg.content:
            print(f"?? AI: {msg.content.strip()}\n")
            
        # Print the actual tool executions and results
        elif msg.type == "tool":
            print(f"??? Tool Execution ({msg.name}): {msg.content}\n")
            
        # Extract and print the final JSON payload
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            for tool in msg.tool_calls:
                if tool["name"] == "RemediationPayload":
                    print("=" * 40)
                    print("?? FINAL DIAGNOSIS PAYLOAD ??")
                    print(tool["args"])
                    print("=" * 40)
    print("\n")
