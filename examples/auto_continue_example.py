"""
Example script demonstrating the auto-continue feature of G4F.

This script uses the Blackbox provider (known for truncating long responses)
and demonstrates how G4F can automatically detect and continue incomplete responses.
"""
import asyncio
import argparse
import g4f
import logging

# Enable logging for the auto-continue module
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("g4f.completions.auto_continue")
logger.setLevel(logging.INFO)

async def generate_with_autocontinue():
    """Generate a response using the auto-continue feature."""
    query = """Write a detailed explanation of quantum computing, covering:
1. Basic principles and how it differs from classical computing
2. The concept of qubits and quantum superposition
3. Quantum entanglement and its significance
4. Current challenges in building quantum computers
5. Potential applications and future prospects
6. Major companies and research institutions in the field
7. Timeline of significant developments in quantum computing
8. Quantum algorithms and their advantages over classical algorithms

Make this extremely comprehensive and include technical details."""

    print("\n=== Using Auto-Continue (Enabled) ===")
    print(f"Query: {query[:100]}...\n")
    
    response = await g4f.ChatCompletion.create_async(
        model="gpt-4o-mini",
        provider="Blackbox",
        auto_continue=True,
        completion_model="claude-3.7-sonnet",  # Using Claude to check completeness
        messages=[{"role": "user", "content": query}]
    )
    
    print(f"Response (Auto-Continue Enabled):\n{response}\n")
    
    print("\n=== Using Standard Request (No Auto-Continue) ===")
    response_no_continue = await g4f.ChatCompletion.create_async(
        model="gpt-4o-mini",
        provider="Blackbox",
        auto_continue=False,
        messages=[{"role": "user", "content": query}]
    )
    
    print(f"Response (Auto-Continue Disabled):\n{response_no_continue}\n")
    
    # Compare the lengths
    print("\n=== Comparison ===")
    print(f"Length with auto-continue: {len(response)} characters")
    print(f"Length without auto-continue: {len(response_no_continue)} characters")
    print(f"Difference: {len(response) - len(response_no_continue)} more characters with auto-continue")

async def stream_with_autocontinue():
    """Stream a response using the auto-continue feature."""
    query = """Write a detailed analysis of machine learning algorithms, covering:
1. Basic types of machine learning (supervised, unsupervised, reinforcement)
2. Popular algorithms for each type
3. Evaluation metrics and validation techniques
4. Challenges and limitations of current approaches
5. Recent advancements and state-of-the-art techniques
6. Real-world applications across different industries

Make this extremely comprehensive and include technical details."""

    print("\n=== Streaming with Auto-Continue ===")
    print(f"Query: {query[:100]}...\n")
    
    print("Response (streaming):")
    
    # Get streaming response with auto-continue
    stream_response = await g4f.ChatCompletion.create_async(
        model="gpt-4o-mini",
        provider="Blackbox",
        auto_continue=True,
        stream=True,
        messages=[{"role": "user", "content": query}]
    )
    
    # Print streaming response chunks
    full_response = ""
    async for chunk in stream_response:
        print(chunk, end="", flush=True)
        full_response += chunk
    
    print("\n\n=== Streaming Complete ===")
    print(f"Total response length: {len(full_response)} characters")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Demonstrate G4F auto-continue feature")
    parser.add_argument("--stream", action="store_true", help="Use streaming response")
    args = parser.parse_args()
    
    if args.stream:
        asyncio.run(stream_with_autocontinue())
    else:
        asyncio.run(generate_with_autocontinue()) 