# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import google.auth
from dotenv import load_dotenv, find_dotenv

# Load workspace and local environment variables
load_dotenv(find_dotenv())

# Setup API Key fallback if not authenticated to Google Cloud
api_key = os.environ.get("GEMINI_API_KEY")
if api_key:
    os.environ["GOOGLE_API_KEY"] = api_key
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
else:
    try:
        _, project_id = google.auth.default()
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    except Exception:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import Workflow, START
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.agents.context import Context
from google.genai import types
from pydantic import BaseModel, Field


# Define schemas
class Classification(BaseModel):
    is_shipping_related: bool = Field(
        description="True if the user query is about shipping topics (rates, tracking, delivery, returns). False otherwise."
    )
    reasoning: str = Field(
        description="A brief explanation of why the query is classified this way."
    )


# Define prompt instructions
classifier_instruction = """You are a query classifier for a shipping company.
Analyze the user's input and determine if it is related to shipping operations.
Shipping operations include:
- Shipping rates or pricing
- Package tracking
- Delivery status or issues
- Returns or refunds of shipped goods

Provide the classification in the required schema format.
If the query is clearly about shipping (e.g. rates, tracking, delivery, returns), set is_shipping_related to True.
Otherwise (e.g. general questions, math, programming, unrelated conversation), set is_shipping_related to False.
"""

faq_instruction = """You are a helpful customer support representative for a shipping company.
Your goal is to answer user queries about shipping rates, tracking, delivery, and returns.

Here are some standard shipping policies to guide your answers:
- Tracking: Customers can track shipments using their 10-digit tracking number on our website.
- Rates: Ground shipping starts at $5.00, Express shipping starts at $15.00. Rates depend on weight and destination.
  Highlight that we offer FREE shipping on orders over $50.00! 🎉
- Delivery: Deliveries occur Monday through Saturday, 8 AM to 8 PM.
- Returns: Shipments can be returned within 30 days of delivery. Return labels can be printed from the customer portal.

Answer the user's question accurately. When discussing shipping rates, make your response super playful, enthusiastic, loaded with fun emojis, and clearly highlight the awesome FREE shipping threshold on orders over $50.00! 🚀📦✨
"""

# Reusable model config
model = Gemini(
    model="gemini-2.5-flash",
    retry_options=types.HttpRetryOptions(attempts=3),
)


# Nodes implementation
def process_start(node_input: types.Content) -> Event:
    """Extracts the user message text and saves it to session state."""
    query_text = ""
    if node_input and node_input.parts:
        query_text = node_input.parts[0].text
    return Event(
        output=query_text, actions=EventActions(state_delta={"user_query": query_text})
    )


classifier = LlmAgent(
    name="classifier",
    model=model,
    instruction=classifier_instruction,
    output_schema=Classification,
)


def router_node(ctx: Context, node_input: dict) -> Event:
    """Routes based on query classification output and forwards user query."""
    is_shipping = node_input.get("is_shipping_related", False)
    route = "shipping" if is_shipping else "unrelated"
    user_query = ctx.state.get("user_query", "")
    return Event(output=user_query, actions=EventActions(route=route))


shipping_faq_agent = LlmAgent(
    name="shipping_faq_agent",
    model=model,
    instruction=faq_instruction,
)


def decline_node(node_input: str):
    """Politely declines to answer unrelated queries."""
    message = "I apologize, but I am only able to answer questions related to shipping (such as tracking, rates, delivery, and returns). How can I assist you with your shipping needs today?"
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=message)])
    )
    yield Event(output=message)


# Build workflow
root_agent = Workflow(
    name="customer_support_workflow",
    edges=[
        (START, process_start),
        (process_start, classifier),
        (classifier, router_node),
        (router_node, {"shipping": shipping_faq_agent, "unrelated": decline_node}),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
