from typing import List, Dict, Any
from app.schemas.voting_models import VotingResult

class VotingService:
    """
    Service responsible for determining the best assignee for a Jira ticket.
    Instead of using expensive LLM calls, this service implements a weighted 
    frequency analysis based on semantic similarity scores retrieved from Qdrant.
    """

    async def get_voting_decision(
        self, 
        similar_issues: List[Dict[str, Any]]
    ) -> VotingResult:
        """
        Analyzes historical data to identify the most suitable candidate via weighted voting.
        
        Args:
            similar_issues (List[Dict[str, Any]]): List of neighbors from vector search, 
                each containing 'assignee', 'assignee_id', 'assignee_email', and 'score'.
            
        Returns:
            VotingResult: A validated result containing the winner and confidence metrics.
        """
        
        # Handling the edge case where no similar historical tasks exist
        if not similar_issues:
            return VotingResult(
                recommended_assignee="Unassigned",
                assignee_id="None",
                assignee_email="None",
                confidence_score=0.0,
                reasoning="No historical context found for comparison.",
                total_tasks_found=0
            )

        # 1. Initialize stats aggregation
        # We track total scores and frequency count per assignee
        assignee_stats = {}
        total_similarity_sum = 0.0

        for issue in similar_issues:
            name = issue.get('assignee', 'Unknown')
            assignee_id = issue.get('assignee_id', 'None')
            assignee_email = issue.get('assignee_email', 'None')
            score = issue.get('score', 0.0)
            
            total_similarity_sum += score

            if name not in assignee_stats:
                assignee_stats[name] = {
                    "total_score": 0.0, 
                    "count": 0, 
                    "id": assignee_id,
                    "email": assignee_email
                }
            
            # Weighted Voting Logic: 
            # Issues with higher similarity scores (closer vectors) exert more influence 
            # on the final recommendation than distant ones.
            assignee_stats[name]["total_score"] += score
            assignee_stats[name]["count"] += 1

        # 2. Determine the winner
        # The assignee with the highest aggregate weighted score is chosen
        winner_name = max(assignee_stats, key=lambda k: assignee_stats[k]["total_score"])
        winner_data = assignee_stats[winner_name]

        # 3. Compute Confidence Metrics
        # Confidence is the ratio of the winner's score against the sum of all scores
        confidence = round(winner_data["total_score"] / total_similarity_sum, 2) if total_similarity_sum > 0 else 0.0
        
        # Constructing a human-readable explanation for the Slack notification
        reasoning = (
            f"Automated selection of {winner_name} based on {winner_data['count']} "
            f"statistically similar historical tasks. Total weighted score: {round(winner_data['total_score'], 2)}."
        )

        return VotingResult(
            recommended_assignee=winner_name,
            assignee_id=winner_data["id"],
            assignee_email=winner_data["email"],
            confidence_score=confidence,
            reasoning=reasoning,
            total_tasks_found=len(similar_issues)
        )