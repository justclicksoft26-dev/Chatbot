"""What people asked that the comments do not explain yet.

    python -m tools.comment_gaps            # the most asked unanswered questions, grouped
    python -m tools.comment_gaps --days 7 --limit 20

For each group: write (or fix) the COMMENT ON TABLE / COLUMN that explains the thing asked about, in
profiles/<name>/comments.sql — an unanswered question is a missing comment, never a missing template.
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra import gaps  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=0, help="only the last N days (default: everything kept)")
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()
    groups = gaps.summary(args.limit, args.days)
    if not groups:
        print("لا توجد أسئلة بلا إجابة مسجّلة.")
        return 0
    for i, g in enumerate(groups, 1):
        kinds = "، ".join(f"{gaps.KINDS[k]} ×{n}" for k, n in g["kinds"].items())
        seen = datetime.datetime.fromtimestamp(g["last_seen"]).strftime("%Y-%m-%d")
        print(f"{i:2}. ×{g['count']:<3} ({g['users']} مستخدم، آخر مرة {seen})  {g['sample']}")
        print(f"      {kinds}   كلمات: {' '.join(g['words'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
