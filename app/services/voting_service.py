from typing import List, Dict, Any
from app.schemas.voting_models import VotingResult

class VotingService:
    """
    Service to determine the best assignee for a ticket without using an LLM.
    Uses a weighted frequency analysis based on similarity scores from vector search.
    """

    async def get_voting_decision(
        self, 
        similar_issues: List[Dict[str, Any]]
    ) -> VotingResult:
        """
        Processes a list of similar issues to find the winner via weighted voting.
        
        Args:
            similar_issues: Results from Qdrant containing 'assignee', 'assigneeId', and 'score'.
            
        Returns:
            A VotingResult object with the top candidate and confidence metrics.
        """
        if not similar_issues:
            return VotingResult(
                recommendedAssignee="Unassigned",
                assigneeId="None",
                confidenceScore=0.0,
                reasoning="No historical context found for comparison.",
                totalTasksFound=0
            )

        # 1. Aggregate scores and occurrences for each assignee
        assignee_stats = {}
        total_similarity_sum = 0.0

        for issue in similar_issues:
            name = issue.get('assignee', 'Unknown')
            user_id = issue.get('assigneeId', 'None')
            score = issue.get('score', 0.0)
            
            total_similarity_sum += score

            if name not in assignee_stats:
                assignee_stats[name] = {
                    "total_score": 0.0, 
                    "count": 0, 
                    "id": user_id
                }
            
            # Applying weighted vote: tickets with higher similarity have more influence
            assignee_stats[name]["total_score"] += score
            assignee_stats[name]["count"] += 1

        # 2. Identify the winner based on the highest aggregate score
        winner_name = max(assignee_stats, key=lambda k: assignee_stats[k]["total_score"])
        winner_data = assignee_stats[winner_name]

        # 3. Calculate final confidence metric
        confidence = round(winner_data["total_score"] / total_similarity_sum, 2) if total_similarity_sum > 0 else 0.0
        
        reasoning = (
            f"Automated selection of {winner_name} based on {winner_data['count']} "
            f"statistically similar historical tasks. Total weighted score: {round(winner_data['total_score'], 2)}."
        )

        return VotingResult(
            recommendedAssignee=winner_name,
            assigneeId=winner_data["id"],
            confidenceScore=confidence,
            reasoning=reasoning,
            totalTasksFound=len(similar_issues)
        )