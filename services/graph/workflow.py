from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from .state import ReceptionistState
from .nodes import (
    extraction_node,
    onboarding_node,
    booking_node,
    faq_node,
    general_node,
    booking_tools,
    faq_tools,
)
from langgraph.checkpoint.memory import MemorySaver

# Tool execution nodes
booking_tool_node = ToolNode(booking_tools)
faq_tool_node = ToolNode(faq_tools)


def route_after_extraction(state: ReceptionistState):
    """Decides where to go after extracting info."""
    if not state.get("onboarding_complete"):
        return "onboarding"

    intent = state.get("intent", "general").lower()
    if "book" in intent:
        return "booking"
    elif "faq" in intent or "insurance" in intent:
        return "faq"
    return "general"


def route_after_booking(state: ReceptionistState):
    """If booking_node returned a tool call, run the tool."""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "booking_tools"
    return END


def route_after_faq(state: ReceptionistState):
    """If faq_node returned a tool call, run the tool."""
    last_msg = state["messages"][-1]
    if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
        return "faq_tools"
    return END


# Build the Graph
workflow = StateGraph(ReceptionistState)

# Add Nodes
workflow.add_node("extractor", extraction_node)
workflow.add_node("onboarding", onboarding_node)
workflow.add_node("booking", booking_node)
workflow.add_node("faq", faq_node)
workflow.add_node("general", general_node)
workflow.add_node("booking_tools", booking_tool_node)
workflow.add_node("faq_tools", faq_tool_node)

# Set Entry
workflow.set_entry_point("extractor")

# Add Conditional Edges from Extractor
workflow.add_conditional_edges(
    "extractor",
    route_after_extraction,
    {
        "onboarding": "onboarding",
        "booking": "booking",
        "faq": "faq",
        "general": "general",
    },
)

# Edges for simple nodes
workflow.add_edge("onboarding", END)
workflow.add_edge("general", END)

# Edges for tools
workflow.add_conditional_edges("booking", route_after_booking)
workflow.add_edge("booking_tools", "booking")  # Loop back after tool execution

workflow.add_conditional_edges("faq", route_after_faq)
workflow.add_edge("faq_tools", "faq")  # Loop back after tool execution

# Compile with Checkpointer
memory = MemorySaver()
app = workflow.compile(checkpointer=memory)
