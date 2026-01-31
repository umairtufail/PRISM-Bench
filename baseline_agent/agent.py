"""
PRISM Baseline Purple Agent

A simple agent that demonstrates how to be evaluated by PRISM.
This agent uses a basic LLM without any cultural awareness training,
expected to score ~60-70% on the benchmark.

This serves as:
1. A demonstration of A2A protocol compliance
2. A baseline for comparison with culturally-aware agents
3. A test target during development
"""

import os
import argparse
import uvicorn
from dotenv import load_dotenv

from groq import Groq
GROQ_AVAILABLE = True
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


class BaselineAgent:
    """A simple LLM agent without cultural awareness training."""

    def __init__(self):
        # Use Groq with GPT-OSS-120B
        groq_key = os.getenv("GROQ_API_KEY")
        
        if not groq_key:
            raise ValueError("GROQ_API_KEY environment variable required")
        
        if not GROQ_AVAILABLE:
            raise ValueError("groq package is required. Install with: pip install groq")
        
        self.client = Groq(api_key=groq_key)
        self.model = "openai/gpt-oss-120b"  # GPT-OSS-120B for baseline agent
        self.provider = "groq"

    async def respond(self, message: str) -> str:
        """Generate a response using basic LLM without cultural prompting."""
        system_prompt = """You are a helpful AI assistant. Answer questions directly and concisely.
Provide practical advice based on common knowledge and best practices."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=1,
            max_completion_tokens=8192,
            top_p=1,
            reasoning_effort="medium",
            stream=False,
        )
        return response.choices[0].message.content or ""


class BaselineExecutor(AgentExecutor):
    """Executor for the baseline agent."""

    def __init__(self):
        self.agent = BaselineAgent()

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
    parser = argparse.ArgumentParser(description="Run the PRISM baseline agent.")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=9019, help="Port to bind")
    parser.add_argument("--card-url", type=str, help="URL to advertise")
    args = parser.parse_args()

    skill = AgentSkill(
        id="general_assistant",
        name="General Assistant",
        description="A basic LLM assistant without specialized cultural training.",
        tags=["assistant", "baseline"],
        examples=["Answer questions", "Provide advice"]
    )

    agent_card = AgentCard(
        name="PRISM-Baseline",
        description="Baseline purple agent for PRISM benchmark. Uses a standard LLM "
                    "without cultural awareness training. Expected score: 60-70%.",
        url=args.card_url or f"http://{args.host}:{args.port}/",
        version='1.0.0',
        default_input_modes=['text'],
        default_output_modes=['text'],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill]
    )

    request_handler = DefaultRequestHandler(
        agent_executor=BaselineExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )
    uvicorn.run(server.build(), host=args.host, port=args.port)


if __name__ == '__main__':
    main()
