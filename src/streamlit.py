import streamlit as st
from AI_Scope_Agent.basic_agent import graph
from AI_Tools.tools import MyTools

if "messages" not in st.session_state.keys():
    st.session_state["messages"] = [{"role": "assistant", "content": "How may I assist you today?"}]

st.title("Agent")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        
prompt = st.chat_input("Say something")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    
    config = {"configurable": {"thread_id": "2"}}
    output = graph.invoke({"messages": st.session_state.messages,'tools': MyTools().getAllTools()}, config=config)
    st.session_state.messages.append({"role": "assistant", "content": output["messages"][-1].content})
    with st.chat_message("assistant"):
        st.write(output["messages"][-1].content)