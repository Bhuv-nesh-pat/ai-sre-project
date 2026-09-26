import streamlit as st
import uuid
from langchain_core.messages import HumanMessage
from agent.graph import app as agent_app 

st.set_page_config(page_title="AI SRE Agent", page_icon="🚨")
st.title("🤖 Autonomous AI SRE Agent")
st.markdown("Enter an alert or cluster issue below for the agent to investigate.")

# Initialize chat history in session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display previous chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("E.g., Alert: P99 latency is high on frontend"):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Display agent response
    with st.chat_message("assistant"):
        with st.spinner("Investigating cluster telemetry..."):
            config = {"configurable": {"thread_id": str(uuid.uuid4())}}
            result = agent_app.invoke({"messages": [HumanMessage(content=prompt)]}, config=config)
            
            # Extract final response
            final_message = result["messages"][-1].content
            
            # Check if there is a JSON payload tool call
            for msg in result["messages"]:
                if msg.type == "ai" and getattr(msg, "tool_calls", None):
                    for tool in msg.tool_calls:
                        if tool["name"] == "RemediationPayload":
                            final_message = f"**Diagnosis Payload:**\n```json\n{tool['args']}\n```"
            
            st.markdown(final_message)
            st.session_state.messages.append({"role": "assistant", "content": final_message})
