"""
PRISM Culturally-Aware Baseline  Agent

A baseline agent with basic cultural awareness prompting.
Expected to score ~70-80% on PRISM benchmark.
Demonstrates improvement from simple cultural prompting.
"""

import os
import argparse
import uvicorn
from dotenv import load_dotenv

from groq import Groq
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


class CulturallyAwareAgent:
    """An agent with basic cultural awareness prompting."""

    def __init__(self):
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise ValueError("GROQ_API_KEY environment variable required")
        self.client = Groq(api_key=groq_key)
        self.model = "openai/gpt-oss-120b"  # GPT-OSS-120B via Groq

    async def respond(self, message: str) -> str:
        """Generate a response with cultural awareness."""
        system_prompt = """You are a culturally-aware AI assistant. When responding:

1. Consider the cultural context implied in the query
2. Look for subtle cues (honorifics, local terms, specific locations)
3. Respect local norms and values, not just Western defaults
4. When uncertain, acknowledge multiple valid perspectives
5. Avoid stereotyping individuals based on group identity
6. Provide nuanced advice that respects local context"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.7,
            max_completion_tokens=8192,
            top_p=1,
            reasoning_effort="medium",
            stream=False,
        )
        return response.choices[0].message.content or ""


class AwareExecutor(AgentExecutor):
    """Executor for the culturally-aware agent."""

    def __init__(self):
        self.agent = CulturallyAwareAgent()

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
    parser = argparse.ArgumentParser(description="Run the PRISM culturally-aware baseline agent.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=9020, help="Port to bind")
    parser.add_argument("--card-url", type=str, help="URL to advertise")
    args = parser.parse_args()

    skill = AgentSkill(
        id="culturally_aware_assistant",
        name="Culturally-Aware Assistant",
        description="A baseline agent with cultural awareness prompting. Expected score: 70-80%.",
        tags=["assistant", "cultural-awareness", "baseline"],
        examples=["Provide culturally-contextual advice", "Respect local norms"]
    )

    agent_card = AgentCard(
        name="PRISM-Aware-Baseline",
        description="Culturally-aware baseline purple agent for PRISM benchmark. "
                    "Uses basic cultural prompting. Expected score: 70-80%.",
        url=args.card_url or f"http://{args.host}:{args.port}/",
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill]
    )

    request_handler = DefaultRequestHandler(
        agent_executor=AwareExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    uvicorn.run(server.build(), host=args.host, port=args.port)


if __name__ == '__main__':
    main()