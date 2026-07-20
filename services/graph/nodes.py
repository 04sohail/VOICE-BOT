import os
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from .state import ReceptionistState
from .tools import check_availability, book_appointment, check_insurance
from langchain_core.tools import tool
from pydantic import BaseModel, Field

llm = ChatOpenAI(
    model="openai/gpt-4o-mini",
    api_key=os.getenv("OPENROUTER_API_KEY", "dummy_key"),
    base_url="https://openrouter.ai/api/v1",
    temperature=0.3,
    max_tokens=150,
)

BASE_SYSTEM_PROMPT = """You are Boyd, the official receptionist for Dr. Smith's Dental Clinic.
CRITICAL GUARDRAIL: You are ONLY allowed to discuss topics related to the dental clinic (booking appointments, clinic hours, insurance, dental services, and polite greetings). 
If the user asks about ANYTHING else (e.g., programming, machine learning, politics, general knowledge, etc.), you MUST politely refuse to answer, state your role, and steer the conversation back to how you can help them with dental services. Do not provide the answer even if you know it.
Keep all responses conversational, warm, and under 2 sentences."""


# LangChain structured tools
@tool
def tool_check_availability(day: str, rationale: str) -> str:
    """
    Check what times are available for an appointment on a specific day.
    'rationale': You must provide a brief explanation of why you decided to use this tool based on the user's request.
    """
    print(f"\n[{'='*40}]")
    print(f"🛠️  TOOL TRIGGERED: check_availability")
    print(f"🤔  WHY IT WAS USED: {rationale}")
    print(f"📋  ARGUMENTS: day={day}")
    print(f"[{'='*40}]\n")
    return check_availability(day)


@tool
def tool_book_appointment(
    patient_name: str, patient_location: str, day: str, time: str, rationale: str
) -> str:
    """
    Book an appointment for a patient on a specific day and time.
    'rationale': You must provide a brief explanation of why you decided to use this tool based on the user's request.
    """
    print(f"\n[{'='*40}]")
    print(f"🛠️  TOOL TRIGGERED: book_appointment")
    print(f"🤔  WHY IT WAS USED: {rationale}")
    print(f"📋  ARGUMENTS: patient={patient_name}, location={patient_location}, day={day}, time={time}")
    print(f"[{'='*40}]\n")
    return book_appointment(patient_name, patient_location, day, time)


@tool
def tool_check_insurance(provider: str, rationale: str) -> str:
    """
    Check if the clinic accepts a specific insurance provider.
    'rationale': You must provide a brief explanation of why you decided to use this tool based on the user's request.
    """
    print(f"\n[{'='*40}]")
    print(f"🛠️  TOOL TRIGGERED: check_insurance")
    print(f"🤔  WHY IT WAS USED: {rationale}")
    print(f"📋  ARGUMENTS: provider={provider}")
    print(f"[{'='*40}]\n")
    return check_insurance(provider)


booking_tools = [tool_check_availability, tool_book_appointment]
faq_tools = [tool_check_insurance]

booking_llm = llm.bind_tools(booking_tools)
faq_llm = llm.bind_tools(faq_tools)


class ExtractedInfo(BaseModel):
    name: str = Field(description="The patient's name, if mentioned")
    location: str = Field(description="The patient's location, if mentioned")
    intent: str = Field(description="The user's intent: 'booking', 'faq', or 'general'")


def extraction_node(state: ReceptionistState):
    """Silent node that extracts variables from the conversation."""
    sys_msg = SystemMessage(
        content="Extract the user's name, location, and intent from the conversation."
    )

    # Simple extraction using LLM structured output
    extractor = llm.with_structured_output(ExtractedInfo)
    try:
        # Pass the last few messages to figure out intent and name
        messages_to_analyze = [sys_msg] + state["messages"][-3:]
        result = extractor.invoke(messages_to_analyze)

        patient_name = state.get("patient_name") or result.name
        patient_location = state.get("patient_location") or result.location

        # If we just extracted it, update it
        if patient_name == "":
            patient_name = None
        if patient_location == "":
            patient_location = None

        onboarding_complete = bool(patient_name and patient_location)

        return {
            "patient_name": patient_name,
            "patient_location": patient_location,
            "onboarding_complete": onboarding_complete,
            "intent": result.intent,
        }
    except:
        return {}


def onboarding_node(state: ReceptionistState):
    """Handles greeting and collecting mandatory info."""
    sys_msg = SystemMessage(
        content=f"{BASE_SYSTEM_PROMPT}\n\n"
        f"Currently known name: {state.get('patient_name')}. "
        f"Currently known location: {state.get('patient_location')}. "
        "Your ONLY goal right now is to politely ask the user for their name and location if they haven't provided both. "
        "If you have both, just say 'Thanks! How can I help you today?'"
    )

    response = llm.invoke([sys_msg] + state["messages"])
    return {"messages": [response]}


def booking_node(state: ReceptionistState):
    """Handles checking slots and booking."""
    sys_msg = SystemMessage(
        content=f"{BASE_SYSTEM_PROMPT}\n\n"
        f"Patient Name: {state.get('patient_name')}. Location: {state.get('patient_location')}. "
        "You must use the provided tools to check availability and book appointments. "
        "IMPORTANT: Our database ONLY stores availability by Day of the Week ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'). "
        "You MUST query the tool using exactly these day names, NOT specific calendar dates (like 'October 12th'). "
        "If a patient asks for a date, politely ask them which day of the week they prefer, or convert it yourself if possible. "
        "When booking, use the patient name and location you already know. Do not ask for them again."
    )

    response = booking_llm.invoke([sys_msg] + state["messages"])
    return {"messages": [response]}


def faq_node(state: ReceptionistState):
    """Handles general clinic questions like insurance."""
    sys_msg = SystemMessage(
        content=f"{BASE_SYSTEM_PROMPT}\n\n"
        "Use your tools to check if we accept their insurance."
    )

    response = faq_llm.invoke([sys_msg] + state["messages"])
    return {"messages": [response]}


def general_node(state: ReceptionistState):
    """Handles basic chit-chat."""
    sys_msg = SystemMessage(
        content=f"{BASE_SYSTEM_PROMPT}\n\n"
        "Politely answer greetings or handle small talk, but strictly adhere to the guardrails if they ask off-topic questions."
    )
    response = llm.invoke([sys_msg] + state["messages"])
    return {"messages": [response]}
