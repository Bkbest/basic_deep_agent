# Mastering LangMem's `summarize_messages` for Production AI Agents

## A Practical Guide to Message Summarization with Proper Token Budget Management

If you're building AI agents that handle long conversations, you've likely faced the challenge of managing context windows while keeping your LLM responsive and accurate. That's where LangMem's `summarize_messages` comes in — but getting it to work properly in production requires understanding several subtle behaviors that the documentation doesn't make obvious.

In this article, I'll share what I've learned from implementing LangMem in a production agent, complete with real code examples and practical tips that took me days of experimentation to discover.

---

## 1. Customizing Summary Prompts for Your Agent's Domain

One of the first things you'll want to do is customize the default summary prompts. By default, LangMem uses generic prompts like "Create a summary of the conversation above." But what if your agent has special responsibilities, like creating sandboxes or maintaining specific state across conversations?

Here's how I override the default prompts in my `nodes.py`:

```python
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langmem.short_term import asummarize_messages

DEFAULT_INITIAL_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("placeholder", "{messages}"),
        ("user", "Create a summary of the conversation above. If a sandbox was created during the conversation, you must include sandbox id in the summary and mention not to create a new sandbox."),
    ]
)

DEFAULT_EXISTING_SUMMARY_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("placeholder", "{messages}"),
        (
            "user",
            "This is summary of the conversation so far: {existing_summary}\n\n"
            "Extend this summary by taking into account the new messages above. If a sandbox ID was created during the conversation summary and history, you must include sandbox id(s) in the summary and mention not to create a new sandbox.",
        ),
    ]
)
```

**Why this matters:** In my agent, sandbox creation is a critical capability. If the summary doesn't remember that a sandbox was already created, the agent might try to create duplicate sandboxes — wasting resources and potentially causing conflicts. By customizing the prompt to explicitly ask for sandbox information, I ensure the summarizer includes this crucial context.

---

## 2. The SystemMessage Inclusion Question

You might wonder whether to include `SystemMessage` in your messages before calling `summarize_messages`. The answer: it's optional, but with important caveats.

LangMem actually ignores `SystemMessage` during the summarization process — it won't try to summarize your system prompt. However, there's a subtle behavior you need to be aware of:

**`summarize_messages` replaces the summarized messages with a single `SystemMessage` in the output.**

This means if your original messages contained a `SystemMessage`, and you had other messages that got summarized, your final invoke call might end up with multiple `SystemMessage` objects.

Some LLM providers don't handle multiple system messages well. If that's your case, you'll need to convert the extra system messages to `AIMessage` before calling your LLM:

```python
# Check if there are exactly two system messages after summarization
system_message_indices = [i for i, msg in enumerate(messags_after_summarization) if isinstance(msg, SystemMessage)]
if len(system_message_indices) == 2:
    second_system_idx = system_message_indices[1]
    # Convert the second system message to an AIMessage
    messags_after_summarization[second_system_idx] = AIMessage(content=messags_after_summarization[second_system_idx].content)
```

---

## 3. The HumanMessage Requirement

Here's a gotcha that cost me hours of debugging: **some models fail when the message list contains only `SystemMessage` objects without any `HumanMessage`**. Especially if you are using Ollama with  minimax-m2.7:cloud.

This can happen after summarization when LangMem collapses everything into system messages. When you then try to invoke your LLM with just system messages, you might get an error like:

```
  raise ResponseError(e.response.text, e.response.status_code) from None
ollama._types.ResponseError: Service Temporarily Unavailable (status code: 503)
```

My workaround was to manually insert a `HumanMessage` before invoking the LLM:

```python
human_msg = HumanMessage(content="Look at the summary and the conversation below and decide what to do next.")
messags_after_summarization.insert(second_system_idx, human_msg)
```

This ensures the model always sees at least one human message, which is especially important for chat-oriented models like those from Ollama.

---

## 4. Understanding When Summarization Actually Happens

A common misconception is that `summarize_messages` summarizes on every call. **It doesn't.**

LangMem uses a token counter that approximately calculates the total tokens in your messages on each agent loop. Summarization is only triggered when this count crosses the `max_tokens_before_summary` threshold.

If your messages are under this threshold, `summarize_messages` simply passes through the existing messages unchanged. This is actually efficient — you don't want to summarize every single turn, as summarization itself uses tokens and can introduce artifacts.

Here's the flow:

```
Agent Loop Start
    ↓
Calculate token count in messages
    ↓
Token count < max_tokens_before_summary?
    → Yes: Skip summarization, use messages as-is
    → No: Trigger summarization process
    ↓
Return summarized messages
```

---

## 5. The Role of `max_tokens`

The `max_tokens` parameter serves a specific purpose: **ensuring the chunk of messages being summarized fits within your summarization LLM's context window**.

When summarization is triggered, LangMem looks at the messages that exceed `max_tokens_before_summary` and ensures that the portion being sent to the summarization LLM fits within `max_tokens`. If a message is too long, LangMem will intelligently trim its content to make it fit.

Here's the key insight: `max_tokens` is about the **summarization LLM's context limit**, not your main LLM's limit. These are often the same model, but conceptually they serve different purposes.

```python
summarization_result = await asummarize_messages(
    state["messages"],
    running_summary=state.get("summary"),
    model=llm,  # This is your summarization model
    max_tokens=40000,  # Budget for the summarization LLM
    max_tokens_before_summary=20000,  # Threshold to trigger summarization
    max_summary_tokens=1000,  # Budget for the summary text itself
    initial_summary_prompt=DEFAULT_INITIAL_SUMMARY_PROMPT,
    existing_summary_prompt=DEFAULT_EXISTING_SUMMARY_PROMPT,
)
```

---

## 6. The Danger of Misconfigured Token Limits

This is the most important practical tip in this article, and it's what caused me the most grief.

**If you set `max_tokens` too close to `max_tokens_before_summary`, you can create a situation where LangMem has to trim even the HumanMessage — leading to failed summarization.**

This commonly happens with research agents that have long loops. Consider an agent tasked with "create a research report about why people celebrate Christmas." This agent might loop extensively, performing web searches, analysis, and writing. After many iterations, the message history becomes very long.

When the last message crosses both thresholds simultaneously, LangMem tries to trim messages to fit within `max_tokens`. If it ends up trimming everything including the HumanMessage, you get this warning:

```
"Failed to trim messages to fit within max_tokens limit before summarization - "
"falling back to the original message list. "
"This may lead to exceeding the context window of the summarization LLM."
```

And summarization simply doesn't happen — your agent continues with an ever-growing message list that will eventually exceed context limits.

**An additional requirement: LangMem needs a HumanMessage to summarize.** Internally, LangMem's `trim_messages` uses  `end_on="human"` to ensure the message window it selects for summarization ends with a HumanMessage. This is by design — the summarizer needs conversational context to generate an accurate summary. If the messages that caused you to exceed `max_tokens_before_summary` (and fall under `max_tokens`) don't contain a HumanMessage at all, LangMem will not be able to summarize them. It will instead fall back to the original message list with the warning above.

This is yet another reason why proper token limit configuration is critical — if your limits are too tight, you might end up with a message window that lacks a HumanMessage, making summarization impossible.

**The fix:** Keep `max_tokens` and `max_tokens_before_summary` far enough apart to give LangMem room to work. For research agents with long loops, I recommend:

- `max_tokens_before_summary`: 15,000–20,000 tokens
- `max_tokens`: 35,000–40,000 tokens

This gives LangMem roughly 20,000 tokens of buffer to select the right messages for summarization without having to trim critical context, and ensures there's almost always a HumanMessage in the selected window.

---

## 7. Experimentation Is Key

Every agent is different. The token counts depend on:

- Your average message length
- Your model's context window
- How your agent's loops work
- Whether you're using tools and how verbose tool results are

**I strongly recommend extensive testing before production deployment.** Here's my testing approach:

1. Start with conservative token limits
2. Run your agent through typical conversation paths
3. Monitor the logs for the "Failed to trim messages" warning
4. Adjust limits based on actual behavior
5. Test edge cases (very long messages, very long conversations)

For my research agent, I went through days of iterations before finding the right balance. The cost was worth it — the agent now handles 100+ turn conversations without issues.

---

## 8. The Running Summary State

One final piece that's easy to overlook: **LangMem tracks summarized messages through its state object**.

You need to persist the `running_summary` in your agent's state:

```python
class State(AgentState):
    todos: list[Todo]
    files: Annotated[dict[str, str], file_reducer]
    summary: RunningSummary | None  # This is critical for LangMem
    current_date: str
    skills_description: str
```

And when you update state after summarization:

```python
state_update = {"messages": [response]}
if summarization_result.running_summary:
    state_update["summary"] = summarization_result.running_summary
return state_update
```

The `running_summary` contains:
- The text of the latest summary
- IDs of messages that were previously summarized
- ID of the last message that was summarized

Without persisting this, LangMem would try to re-summarize already-summarized messages, wasting tokens and potentially creating inconsistent summaries.

---

## Putting It All Together

Here's the complete pattern from my `nodes.py`:

```python
async def llm_with_tools(state: State, runtime: Runtime):
    # Create system message and prepend to messages
    agent_description = AGENT_DESCRIPTION
    prompt = PromptTemplate.from_template(agent_description)
    system_message = [SystemMessage(content=prompt.format(
        current_date=state["current_date"], 
        skills_description=state["skills_description"]
    ))]
    state["messages"] = system_message + state["messages"]
    
    # Summarize messages if needed
    summarization_result = await asummarize_messages(
        state["messages"],
        running_summary=state.get("summary"),
        model=llm,
        max_tokens=40000,
        max_tokens_before_summary=20000,
        max_summary_tokens=1000,
        initial_summary_prompt=DEFAULT_INITIAL_SUMMARY_PROMPT,
        existing_summary_prompt=DEFAULT_EXISTING_SUMMARY_PROMPT,
    )
    messags_after_summarization = summarization_result.messages
    
    # Handle multiple system messages (convert extras to AIMessage)
    system_message_indices = [i for i, msg in enumerate(messags_after_summarization) 
                             if isinstance(msg, SystemMessage)]
    if len(system_message_indices) == 2:
        second_system_idx = system_message_indices[1]
        messags_after_summarization[second_system_idx] = AIMessage(
            content=messags_after_summarization[second_system_idx].content
        )
        # Insert HumanMessage for models that require it
        human_msg = HumanMessage(content="Look at the summary and the conversation below and decide what to do next.")
        messags_after_summarization.insert(second_system_idx, human_msg)
    
    # Invoke LLM with summarized messages
    response = await llm_tools.ainvoke(messags_after_summarization)
    
    # Update state with response and running summary
    state_update = {"messages": [response]}
    if summarization_result.running_summary:
        state_update["summary"] = summarization_result.running_summary
    
    return state_update
```

---

## Conclusion

LangMem's `summarize_messages` is a powerful tool for building long-running AI agents, but it requires careful configuration to work correctly. The key takeaways are:

1. **Customize your prompts** to include domain-specific information the summarizer should know
2. **Handle multiple system messages** by converting extras to AIMessage
3. **Always include a HumanMessage** if your model requires it
4. **Understand when summarization triggers** — it's based on `max_tokens_before_summary`
5. **Set `max_tokens` appropriately** for your summarization LLM
6. **Keep token limits apart** to avoid the trimming trap
7. **Test extensively** with your specific use case
8. **Persist the running summary** in your state

Get these right, and you'll have an agent that can handle conversations of virtually unlimited length while staying within context window limits.

---

## Import Statements and Versions

Here's everything you need to copy-paste to get started:

```python
# Core LangMem imports
from langmem.short_term import asummarize_messages, summarize_messages, RunningSummary

# LangChain imports for messages and prompts
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate

# Your LLM setup (example with Ollama)
from langchain_ollama import ChatOllama
```

**Versions used in this article:**

| Package | Version |
|---------|---------|
| langchain | 1.2.10 |
| langchain-ollama | 1.0.1 |
| langmem | 0.0.30 |

**Model used:** `minimax-m2.7:cloud` (Ollama Pro)

---

## Further Reading

For the API reference and official documentation, visit:
**[LangMem Short Term Reference](https://langchain-ai.github.io/langmem/reference/short_term/)**

---

*Have questions or your own tips for using LangMem? I'd love to hear them. Drop a comment below!*