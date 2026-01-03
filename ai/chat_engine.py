from ai.tool_knowledge import TOOL_KNOWLEDGE

SYSTEM_PROMPT = """
You are a bioinformatics assistant for a Nanopore genome analysis pipeline.
You explain tools clearly to biologists and students.
You never execute commands or modify files.
"""

def build_prompt(user_message: str) -> str:
    context = ""

    for tool, info in TOOL_KNOWLEDGE.items():
        if tool in user_message.lower():
            context += f"""
Tool: {tool}
Purpose: {info['purpose']}
Input: {info['input']}
Output: {info['output']}
Explanation: {info['explanation']}
"""

    return f"""
{SYSTEM_PROMPT}

{context}

User question:
{user_message}

Answer clearly in simple language.
"""
