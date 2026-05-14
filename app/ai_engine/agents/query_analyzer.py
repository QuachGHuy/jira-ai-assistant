from datetime import datetime
from typing import Optional, Dict
from langchain_openai import ChatOpenAI
from app.schemas.tool_models import SearchInput

class QueryAnalyzer:
    def __init__(self, llm: ChatOpenAI):
        self.analyzer = llm.with_structured_output(SearchInput)

    async def analyze(self, user_input: str) -> SearchInput:
        now = datetime.now()
        current_context = now.strftime("%A, %b %d, %Y") 
        system_prompt = f"""
            Role: Senior Jira Analyst. Parse queries to JSON for Hybrid Vector Search (Qdrant).
            
            # Context
            - Today: {current_context}
            - Current Year: {now.year}
            - Rules: Relative dates (today, last week, etc.) must be calculated from today. Use ISO 8601.
            - Metadata: Case-sensitive (e.g., "Done").

            # Output Schema (Return exact JSON)
            1. "input" (String): Semantic topic/ID.
            2. "filter" (Object): Qdrant "must" structure.

            # Metadata Mapping
            - ID: metadata.key (Keyword: "APG-127")
            - Project: metadata.project (Keyword: "Others")
            - Owner: metadata.owner (Keyword: "email@workforceoptimizer.com")
            - Status: metadata.status (Keyword: "To Do", "Done")
            - Priority: metadata.priority (Keyword: "S1-Critical")
            - Type: metadata.type (Keyword: "Bug", "Task")
            - Date: metadata.created_at (Date range)

            # Constraints
            1. Split Mandate: "input" = Intent/Topic. "filter" = Strict metadata. No semantic terms in filter.
            2. ID Rule: If Ticket ID (e.g., APG-144) is found, put it in BOTH "input" and "metadata.key".
            3. Dates: Convert "since Monday" or "last month" to "range" {{ "gte": "ISO-DATE" }}.

            # Examples
            User: "Find login bugs in project Others"
            Result: {{"input": "login problems", "filter": {{"must": [{{"key": "metadata.project", "match": {{"value": "Others"}}}}, {{"key": "metadata.type", "match": {{"value": "Bug"}}}}]}}}}

            User: "Check APG-127"
            Result: {{"input": "APG-127", "filter": {{"must": [{{"key": "metadata.key", "match": {{"value": "APG-127"}}}}]}}}}

            User: "Tasks by Huy since yesterday"
            Result: {{"input": "assigned tasks", "filter": {{"must": [{{"key": "metadata.owner", "match": {{"value": "huy@workforceoptimizer.com"}}}}, {{"key": "metadata.created_at", "range": {{"gte": "2026-05-13T00:00:00Z"}}}}]}}}}
        """
        
        return await self.analyzer.ainvoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ])