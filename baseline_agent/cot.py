"""
PRISM Chain-of-Thought Baseline Purple Agent

A baseline agent with explicit reasoning steps for cultural analysis.
Expected to score ~75-85% on PRISM benchmark.
Demonstrates best-practice prompting with structured thinking.
"""

import os
import argparse
import uvicorn
from dotenv import load_dotenv

from google import genai
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    Task,
    TaskState,
    UnsupportedOperationError,
)
from a2a.utils import get_message_text, new_agent_text_message, new_task
from a2a.utils.errors import ServerError

load_dotenv()


class CoTAgent:
    """An agent with chain-of-thought reasoning for cultural intelligence."""

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY required")
        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-2.5-flash"

    async def respond(self, message: str) -> str:
        """Generate a response with structured cultural reasoning."""
        system_prompt = """You are a culturally-intelligent AI assistant. For each query, think through:

STEP 1 - Context Detection:
- What location, culture, or group is implied?
- What specific terms or cues indicate the context?
- What local norms might apply?

STEP 2 - Value Analysis:
- What values are prioritized in this context?
- How might they differ from Western defaults?
- What conflicts might exist?

STEP 3 - Response Formulation:
- Provide advice that respects the detected context
- Avoid stereotyping or imposing external norms
- Acknowledge complexity when multiple values conflict
- Offer nuanced, locally-appropriate guidance

Always show your reasoning briefly, then provide the final recommendation."""

        response = self.client.models.generate_content(
            model=self.model,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.7,
            ),
            contents=message,
        )
        return response.text


class CoTExecutor(AgentExecutor):
    """Executor for the chain-of-thought agent."""

    def __init__(self):
        self.agent = CoTAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        msg = context.message
        if not msg:
            return

        task = new_task(msg)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()

        try:
            input_text = get_message_text(msg)
            response = await self.agent.respond(input_text)
            
            await updater.update_status(
                TaskState.working,
                new_agent_text_message(response, context_id=task.context_id, task_id=task.id)
            )
            await updater.complete()
        except Exception as e:
            await updater.failed(
                new_agent_text_message(f"Error: {e}", context_id=task.context_id, task_id=task.id)
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise ServerError(error=UnsupportedOperationError())


def main():
    parser = argparse.ArgumentParser(description="Run the PRISM CoT baseline agent.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=9021, help="Port to bind")
    parser.add_argument("--card-url", type=str, help="URL to advertise")
    args = parser.parse_args()

    skill = AgentSkill(
        id="cot_cultural_assistant",
        name="Chain-of-Thought Cultural Assistant",
        description="A baseline agent with explicit cultural reasoning. Expected score: 75-85%.",
        tags=["assistant", "chain-of-thought", "cultural-reasoning", "baseline"],
        examples=["Analyze cultural context explicitly", "Show reasoning steps"]
    )

    agent_card = AgentCard(
        name="PRISM-CoT-Baseline",
        description="Chain-of-Thought baseline purple agent for PRISM benchmark. "
                    "Uses structured reasoning for cultural analysis. Expected score: 75-85%.",
        url=args.card_url or f"http://{args.host}:{args.port}/",
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill]
    )

    request_handler = DefaultRequestHandler(
        agent_executor=CoTExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    uvicorn.run(server.build(), host=args.host, port=args.port)


if __name__ == '__main__':
    main()