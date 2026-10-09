Rewrite the user's latest message into a standalone question for searching a tech-news database.

Rules:
- Resolve pronouns and references ("it", "they", "that model", "the deal", "what about pricing?") using the conversation.
- Keep the user's intent, time phrases ("yesterday", "this week") and named sources exactly.
- Do not answer. Do not add facts that are not in the conversation.
- If the message is already standalone, return it unchanged.

Return JSON: {"standalone": "..."}
