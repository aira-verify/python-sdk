"""LangChain agent with Aira notarization and trust layer."""
from aira import Aira
from aira.extras.langchain import AiraCallbackHandler

# Note: This example requires: pip install aira-sdk[langchain] langchain-openai
# Set AIRA_API_KEY and OPENAI_API_KEY environment variables

aira = Aira(api_key="aira_live_xxx")  # Replace with your key

# Trust policy — advisory checks enriching each notarization receipt.
# Only block_revoked_vc actually prevents notarization; everything else is informational.
trust_policy = {
    "verify_counterparty": True,      # resolve counterparty DID
    "min_reputation": 60,             # warn if reputation score below 60
    "require_valid_vc": True,         # check Verifiable Credential validity
    "block_revoked_vc": True,         # block if counterparty VC is revoked
    "block_unregistered": False,      # don't block agents without Aira DIDs
}

handler = AiraCallbackHandler(
    client=aira,
    agent_id="langchain-research-agent",
    model_id="gpt-5.2",
    trust_policy=trust_policy,
)

# Every tool call and chain completion gets a cryptographic receipt,
# enriched with trust context (DID resolution, VC validity, reputation score).

from langchain_core.tools import tool
from langchain_core.messages import HumanMessage

@tool
def search_documents(query: str) -> str:
    """Search internal documents."""
    return f"Found 3 documents matching '{query}'"

@tool
def summarize(text: str) -> str:
    """Summarize text."""
    return f"Summary: {text[:100]}..."

# In a real app, you'd create a chain/agent here:
# from langchain_openai import ChatOpenAI
# llm = ChatOpenAI(model="gpt-5.2")
# agent = create_tool_calling_agent(llm, [search_documents, summarize], prompt)
# agent_executor = AgentExecutor(agent=agent, tools=[search_documents, summarize])
# result = agent_executor.invoke(
#     {"input": "Find and summarize our Q1 compliance report"},
#     config={"callbacks": [handler]}
# )

# Simulate what the handler does:
print("Simulating LangChain agent with Aira notarization + trust layer...")
handler.on_tool_end("Found 3 documents", name="search_documents")
handler.on_tool_end("Summary: Q1 compliance is on track", name="summarize")
handler.on_chain_end({"output": "Q1 compliance report summary..."})
print("Done — 3 actions notarized with cryptographic receipts + trust context")
