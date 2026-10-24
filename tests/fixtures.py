"""Synthetic reports for layout tests; these are not real player statistics."""

import base64

ICON = (
    "data:image/svg+xml;base64,"
    + base64.b64encode(
        b'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="48"><rect width="64" height="48" fill="#34506a"/><path d="M10 34L32 10L54 34Z" fill="#ffb85b"/></svg>'
    ).decode()
)


def make_report(count=5, mode="competitive"):
    """Build a complete synthetic report using the service's actual field names."""
    players = []
    for index in range(count):
        tag = f"示例玩家{index + 1}#12345"
        rank = {"known": True, "label": "钻石3", "icon": ICON, "role_label": "输出"}
        matches = []
        for row in range(12):
            matches.append(
                {
                    "begin_ts": 1792810000000 - row * 1200000,
                    "seconds": 610 + row * 20,
                    "team_size": 5,
                    "hero": "示例英雄",
                    "hero_icon": ICON,
                    "role": "dps",
                    "role_label": "输出",
                    "map_icon": ICON,
                    "map_name": f"示例地图 · 第{row + 1}场",
                    "outcome_label": "胜" if row % 4 else "负",
                    "rank": rank,
                    "score": 100 if row == 0 else 82.5,
                    "score_grade": "S" if row == 0 else "A",
                    "grade": "A",
                    "is_mvp": row == 0,
                    "is_carry": row < 8,
                    "is_svp": row == 4,
                    "party": {"known": True, "size": 3, "label": "三排"},
                    "final_blow_share": 0.43,
                    "fleta": 0.86,
                    "stats": {
                        "kill": 28,
                        "assist": 9,
                        "death": 3,
                        "heroDamage": 12500,
                        "cure": 200,
                        "finalHit": 13,
                    },
                    "metrics": {
                        "damage": {
                            "value": 12500,
                            "reference": 9000,
                            "reference_per10": 8000,
                            "comparison": "同位置参考",
                            "contribution": 8.5,
                        }
                    },
                    "kd": 28 / 3,
                    "team_final_blows": 30,
                    "opponent_final_blows": 29,
                    "sample_weight": 1.15,
                    "duration_weight": 1,
                    "balanced_final_blows": True,
                    "long_match": row > 9,
                    "is_stomp": False,
                    "adjustments": [
                        {"points": 12.5, "reason": "持续高Fleta进攻表现"},
                        {"points": -1.5, "reason": "阵亡参考修正"},
                    ],
                    "warnings": [],
                }
            )
        players.append(
            {
                "battletag": tag,
                "rank": index + 1,
                "tier": "上等马" if index < 2 else "中等马" if index < 4 else "下等马",
                "score": 100 if index == 0 else 91 - index * 3,
                "grade": "S" if index < 2 else "A",
                "score_grade": "S" if index < 2 else "A",
                "rated_matches": 12,
                "status": "complete",
                "confidence": 1,
                "primary_role": "dps",
                "matches": matches,
                "errors": [],
                "wins": 9,
                "losses": 3,
                "draws": 0,
                "win_rate": 0.75,
                "final_blow_share": 0.43,
                "fleta": 0.86,
                "kd": 28 / 3,
                "smurf_matches": 8,
                "is_smurf": index == 0,
                "high_kd_matches": 9,
                "mvp_matches": 1,
                "carry_matches": 8,
                "svp_matches": 1,
                "short_matches": 0,
                "long_matches": 2,
                "balanced_matches": 12,
                "stomp_matches": 0,
                "effective_matches": 13.8,
                "sample_note": "合成示例数据 · 仅用于验证长图排版",
                "match_average": 87.5,
                "summary_adjustments": [{"points": 12.5, "reason": "综合参考修正"}],
                "averages": {
                    "damage_per10": 11200,
                    "survival_per10": 2.8,
                    "final_blows_per10": 11.5,
                    "healing_per10": 180,
                },
                "latest_rank": rank,
            }
        )
    return {
        "mode": mode,
        "mode_label": "竞技" if mode == "competitive" else "休闲",
        "players": players,
        "summary": {
            "requested_players": count,
            "complete_players": count,
            "rated_matches": count * 12,
        },
        "summary_text": "我方上等马：示例玩家1(100/F86%)\n我方中等马：示例玩家3(85/F86%)\n合成示例数据，仅供排版验证。",
        "relative_notice": "仅比较本名单各自匹配池近12场；段位跨度过大时上下等马评级无意义。",
    }
