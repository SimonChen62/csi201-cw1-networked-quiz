"""Score calculation and deterministic leaderboard construction.

This module deliberately contains no socket or room-management code. Keeping
the scoring rule pure makes it easy to test and prevents one room's score
state being accidentally reused by another room.
"""

from collections.abc import Mapping
from typing import Any


def build_leaderboard(
    scores: Mapping[str, int],
    player_display_names: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Return a stable, highest-score-first leaderboard.

    Ties are ordered by ``user_id`` so every client sees exactly the same
    result. A player who disconnected during a quiz stays in the result because
    they may have earned points before leaving; later missing answers add zero.
    """
    ordered = sorted(scores, key=lambda user_id: (-scores[user_id], user_id))
    return [
        {
            "rank": rank,
            "user_id": user_id,
            "display_name": player_display_names.get(user_id, user_id),
            "score": scores[user_id],
        }
        for rank, user_id in enumerate(ordered, start=1)
    ]
