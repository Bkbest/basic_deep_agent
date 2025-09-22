"""
This module contains system prompts for different agents in the application.

Each prompt is loaded from its respective text file and stored in a variable with
a descriptive name.
"""

import os
base_dir = os.path.dirname(os.path.abspath(__file__))

# Load tool requirement analyzer prompt
with open(os.path.join(base_dir,"system_prompt_todo_req.txt"), "r", encoding="utf-8") as f:
    system_prompt_agent = f.read()
    
system_prompt_todo_req = system_prompt_agent