"""Merge the link-fetch and vision-page-result migration branches."""

revision = "0014_merge_ingest_link_queue"
down_revision = ("0013_vision_page_results", "0013_link_draft_fetch_queue")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
