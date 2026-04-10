"""LangChain agent with Aira authorization gating.

AiraCallbackHandler wraps each tool call in an authorize → execute →
notarize cycle. If a policy denies a tool call, the handler raises
AiraToolDenied from on_tool_start and the tool never runs.

Install:
    pip install aira-sdk[langchain] langchain-openai

Env:
    AIRA_API_KEY, OPENAI_API_KEY
"""
from aira import Aira
from aira.extras.langchain import AiraCallbackHandler

aira = Aira(api_key="aira_live_xxx")  # Replace with your key

handler = AiraCallbackHandler(
    client=aira,
    agent_id="langchain-research-agent",
    model_id="gpt-5.2",
)

# Every tool call goes through authorize BEFORE it runs. If Aira denies it
# (POLICY_DENIED, ENDPOINT_NOT_WHITELISTED, pending_approval, ...) the
# callback raises and the LangChain agent treats it as a tool error.

from langchain_core.tools import tool  # noqa: E402

@tool
def search_documents(query: str) -> str:
    """Search internal documents."""
    return f"Found 3 documents matching '{query}'"

@tool
def summarize(text: str) -> str:
    """Summarize text."""
    return f"Summary: {text[:100]}..."

# In a real app you'd plug the handler into your chain/agent:
#   from langchain_openai import ChatOpenAI
#   llm = ChatOpenAI(model="gpt-5.2")
#   agent = create_tool_calling_agent(llm, [search_documents, summarize], prompt)
#   agent_executor = AgentExecutor(agent=agent, tools=[search_documents, summarize])
#   result = agent_executor.invoke(
#       {"input": "Find and summarize our Q1 compliance report"},
#       config={"callbacks": [handler]},
#   )

# Simulate the handler lifecycle:
print("Simulating LangChain agent with Aira authorization gating...")
handler.on_tool_start({"name": "search_documents"}, "compliance report", run_id="r1")
handler.on_tool_end("Found 3 documents", run_id="r1", name="search_documents")
handler.on_tool_start({"name": "summarize"}, "Q1 compliance is on track", run_id="r2")
handler.on_tool_end("Summary: Q1 compliance on track", run_id="r2", name="summarize")
handler.on_chain_end({"output": "Q1 compliance report summary..."})
print("Done — 2 tool calls gated + notarized, 1 chain completion audited")
