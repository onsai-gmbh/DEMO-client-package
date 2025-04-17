from pydantic import BaseModel, Field
from typing import Optional, Literal, Union

# -----------------------------------------------
# 1. FAQ Model
# -----------------------------------------------
class FAQResponse(BaseModel):
    mode: Literal["faq"]
    response: str = Field(..., description="Answer the user's question.")
    booking: bool = Field(False, description="The user wants to make a reservation/to book a room.")
    follow_up: Optional[str] = Field(description="If booking is False, make sure to ask if the user has any other questions, varying the question.")

class Booking(BaseModel):
    mode: Literal["booking"]
    booking:  Literal[True]
    arrival_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="The day of arrival.")
    departure_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="The day of departure.")
    number_of_adults: Optional[int] = Field(None, gt=0, description="For how many adults to make the booking.")
    first_name: Optional[str] = Field(None, description="Guest's first name (only one is needed).")
    last_name: Optional[str] = Field(None, description="Guest's first name (only one is needed).")
    guest_whatsapp_number: Optional[str] = Field(None, description="The phone number to send a whatsapp message to. Ask the user if they want to send the confirmation to the current phone number.")
    response: Optional[str] = Field(description="Collect missing data and confirm or deny the booking.")

#children_ages_list: Optional[list] = Field(None, description="List of children's ages. If no children, set to None.")

class BookingValidator(BaseModel):
    mode: Literal["booking"]
    booking:  Literal[True]
    arrival_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="The day of arrival.")
    departure_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="The day of departure.")
    number_of_adults: int = Field(..., gt=0, description="For how many adults to make the booking.")
    first_name: str = Field(..., description="Guest's first name (only one is needed).")
    last_name: str = Field(..., description="Guest's first name (only one is needed).")
    guest_whatsapp_number: str = Field(None, description="The phone number to send a whatsapp message to. Ask the user if they want to send the confirmation to the current phone number.")
    response: Optional[str] = Field(description="Collect missing data and confirm or deny the booking.")
    booking_confirmed: Optional[Literal[True, False, None]] = Field(None, description="The guest confirmed the rbooking.")
#    children_ages_list: Optional[list] = Field(None, description="List of children's ages. If no children, set to None.")

class EmployeeHandover(BaseModel):
    mode: Literal["employee_handover"]
    call_forwarding: Literal[True] = Field(..., description="Hand the conversation over to an employee.")
    emergency_topic: Optional[Literal[True, False]] = Field(None, description="The topic of the emergency, e.g. police, fire, ambulance.")


class Farewell(BaseModel):
    mode: Literal["farewell"] = Field(..., description="The user wants to end the conversation/ doesn't have any more questions.")
    response: str = Field(..., description="Say goodbye to the user adjusting the farewell to the converation via the phone.")

ResponseModel = Union[
    FAQResponse, 
    Booking,
    BookingValidator,
    Farewell,
    EmployeeHandover

]
