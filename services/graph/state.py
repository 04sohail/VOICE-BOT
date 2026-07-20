from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
import operator


class ReceptionistState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    patient_name: str | None
    patient_location: str | None
    onboarding_complete: bool
    intent: str | None
