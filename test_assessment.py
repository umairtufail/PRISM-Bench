#!/usr/bin/env python3
"""
Test PRISM assessment locally using A2A client.
This properly uses the A2A protocol to send assessment requests.
"""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, TextPart
import httpx


async def run_assessment():
    """Run a PRISM assessment locally."""
    
    green_url = "http://127.0.0.1:9009"
    baseline_url = "http://127.0.0.1:9019"
    
    print("🧪 PRISM Local Assessment Test")
    print("=" * 50)
    
    # Check if agents are running
    print("\n🔍 Checking if agents are running...")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            green_response = await client.get(f"{green_url}/.well-known/agent-card.json")
            if green_response.status_code != 200:
                print(f"❌ Green agent not responding (status: {green_response.status_code})")
                return
            green_card = green_response.json()
            print(f"✓ Green agent: {green_card['name']}")
            
            baseline_response = await client.get(f"{baseline_url}/.well-known/agent-card.json")
            if baseline_response.status_code != 200:
                print(f"❌ Baseline agent not responding (status: {baseline_response.status_code})")
                return
            baseline_card = baseline_response.json()
            print(f"✓ Baseline agent: {baseline_card['name']}")
    except Exception as e:
        print(f"❌ Error checking agents: {e}")
        print("\n💡 Make sure both agents are running:")
        print("   Terminal 1: uv run src/server.py --host 127.0.0.1 --port 9009")
        print("   Terminal 2: uv run baseline_agent/agent.py --host 127.0.0.1 --port 9019")
        return
    
    # Create assessment request
    assessment_request = {
        "participants": {
            "evaluee": baseline_url + "/"
        },
        "config": {
            "num_scenarios": 3,  # Small number for quick test
            "test_level": "all"
        }
    }
    
    print(f"\n📤 Sending assessment request...")
    print(f"   Scenarios: {assessment_request['config']['num_scenarios']}")
    print(f"   Level: {assessment_request['config']['test_level']}")
    print()
    
    # Use A2A client to send request
    try:
        async with httpx.AsyncClient(timeout=300.0) as httpx_client:
            resolver = A2ACardResolver(httpx_client=httpx_client, base_url=green_url)
            agent_card = await resolver.get_agent_card()
            
            config = ClientConfig(httpx_client=httpx_client, streaming=True)
            factory = ClientFactory(config)
            client = factory.create(agent_card)
            
            # Create message with assessment request
            msg = Message(
                kind="message",
                role=Role.user,
                parts=[Part(root=TextPart(text=json.dumps(assessment_request)))],
                message_id=uuid4().hex,
            )
            
            # Send and stream responses
            print("⏳ Assessment in progress...")
            print("-" * 50)
            
            event_count = 0
            async for event in client.send_message(msg):
                event_count += 1
                
                # Events are tuples: (task, update)
                if isinstance(event, tuple) and len(event) == 2:
                    task, update = event
                    
                    # Print status
                    if hasattr(task, 'status') and task.status:
                        if hasattr(task.status, 'state'):
                            state = task.status.state.value if hasattr(task.status.state, 'value') else str(task.status.state)
                            if state != 'pending':
                                print(f"📊 Status: {state}")
                    
                    # Print update message
                    if update and hasattr(update, 'parts'):
                        for part in update.parts:
                            if hasattr(part, 'root'):
                                if hasattr(part.root, 'text'):
                                    print(f"📋 {part.root.text}")
                    
                    # Check for artifacts (results)
                    if hasattr(task, 'artifacts') and task.artifacts:
                        print("\n✅ Assessment complete! Results:")
                        print("=" * 50)
                        for artifact in task.artifacts:
                            if hasattr(artifact, 'parts'):
                                for part in artifact.parts:
                                    if hasattr(part, 'root'):
                                        if hasattr(part.root, 'data'):
                                            # JSON data
                                            data = part.root.data
                                            print("\n📈 JSON Results:")
                                            print(json.dumps(data, indent=2))
                                            if isinstance(data, dict):
                                                print(f"\n🎯 Summary: Score={data.get('overall_score', 'N/A')}%, DAR={data.get('level1_dar', 'N/A')}%, SRS={data.get('level2_srs', 'N/A')}%")
                                        elif hasattr(part.root, 'text'):
                                            # Text summary
                                            print("\n📝 Text Summary:")
                                            print(part.root.text)
                else:
                    # Debug: print event type
                    print(f"🔍 Event {event_count}: {type(event)}")
            
            print(f"\n✓ Received {event_count} events")
            
    except Exception as e:
        print(f"\n❌ Error during assessment: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_assessment())
