from app.tools.registry import ToolRegistry


def test_registry_loads_all_configured_tools() -> None:
    registry = ToolRegistry.from_file()

    assert len(registry.specs) == 21
    assert len(registry.names_for_profile("visitor")) == 10
    assert "web_search" not in registry.names_for_profile("visitor")
    assert "web_search" in registry.names_for_profile("team")
    assert "save_research_note" in registry.names_for_profile("cli")
    assert "website_content_search" in registry.names_for_profile("team")
    assert "website_draft_create" not in registry.names_for_profile("team")
    assert "website_draft_create" in registry.names_for_profile(
        "team", include_write=True
    )
    assert "website_published_update" not in registry.names_for_profile(
        "team", write_mode="draft-only"
    )
    assert "website_published_update" in registry.names_for_profile(
        "team", write_mode="draft-and-publish"
    )
    assert "website_publish_draft" in registry.names_for_profile(
        "team", write_mode="draft-and-publish"
    )
