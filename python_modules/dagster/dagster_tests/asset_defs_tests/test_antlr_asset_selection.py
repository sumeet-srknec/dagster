import pytest
from dagster._core.definitions.antlr_asset_selection.antlr_asset_selection import (
    AntlrAssetSelectionParser,
)
from dagster._core.definitions.asset_selection import AssetSelection, CodeLocationAssetSelection
from dagster._core.definitions.decorators.asset_decorator import asset
from dagster._core.storage.tags import KIND_PREFIX


@pytest.mark.parametrize(
    "selection_str, expected_tree_str",
    [
        ("*", "(start (expr *) <EOF>)"),
        ("key:a", "(start (expr (traversalAllowedExpr (attributeExpr key : (value a)))) <EOF>)"),
        (
            "key_substring:a",
            "(start (expr (traversalAllowedExpr (attributeExpr key_substring : (value a)))) <EOF>)",
        ),
        (
            'key:"*/a+"',
            '(start (expr (traversalAllowedExpr (attributeExpr key : (value "*/a+")))) <EOF>)',
        ),
        (
            'key_substring:"*/a+"',
            '(start (expr (traversalAllowedExpr (attributeExpr key_substring : (value "*/a+")))) <EOF>)',
        ),
        (
            "sinks(key:a)",
            "(start (expr (traversalAllowedExpr (functionName sinks) ( (expr (traversalAllowedExpr (attributeExpr key : (value a)))) ))) <EOF>)",
        ),
        (
            "roots(key:a)",
            "(start (expr (traversalAllowedExpr (functionName roots) ( (expr (traversalAllowedExpr (attributeExpr key : (value a)))) ))) <EOF>)",
        ),
        (
            "tag:foo=bar",
            "(start (expr (traversalAllowedExpr (attributeExpr tag : (value foo) = (value bar)))) <EOF>)",
        ),
        (
            'owner:"owner@owner.com"',
            '(start (expr (traversalAllowedExpr (attributeExpr owner : (value "owner@owner.com")))) <EOF>)',
        ),
        (
            'group:"my_group"',
            '(start (expr (traversalAllowedExpr (attributeExpr group : (value "my_group")))) <EOF>)',
        ),
        (
            "kind:my_kind",
            "(start (expr (traversalAllowedExpr (attributeExpr kind : (value my_kind)))) <EOF>)",
        ),
        (
            "code_location:my_location",
            "(start (expr (traversalAllowedExpr (attributeExpr code_location : (value my_location)))) <EOF>)",
        ),
        (
            "(((key:a)))",
            "(start (expr (traversalAllowedExpr ( (expr (traversalAllowedExpr ( (expr (traversalAllowedExpr ( (expr (traversalAllowedExpr (attributeExpr key : (value a)))) ))) ))) ))) <EOF>)",
        ),
        (
            "not key:a",
            "(start (expr not (expr (traversalAllowedExpr (attributeExpr key : (value a))))) <EOF>)",
        ),
        (
            "key:a and key:b",
            "(start (expr (expr (traversalAllowedExpr (attributeExpr key : (value a)))) and (expr (traversalAllowedExpr (attributeExpr key : (value b))))) <EOF>)",
        ),
        (
            "key:a or key:b",
            "(start (expr (expr (traversalAllowedExpr (attributeExpr key : (value a)))) or (expr (traversalAllowedExpr (attributeExpr key : (value b))))) <EOF>)",
        ),
    ],
)
def test_antlr_tree(selection_str, expected_tree_str):
    asset_selection = AntlrAssetSelectionParser(selection_str, include_sources=True)
    assert asset_selection.tree_str == expected_tree_str


@pytest.mark.parametrize(
    "selection_str",
    [
        "+",
        "*+",
        "**key:a",
        "not",
        "key:a key:b",
        "key:a and and",
        "key:a and",
        "sinks",
        "owner",
        "tag:foo=",
        "owner:owner@owner.com",
    ],
)
def test_antlr_tree_invalid(selection_str):
    with pytest.raises(Exception):
        AntlrAssetSelectionParser(selection_str)


@pytest.mark.parametrize(
    "selection_str, expected_assets",
    [
        ("key:a", AssetSelection.assets("a")),
        ('key:"*/a+"', AssetSelection.assets("*/a+")),
        ("key_substring:a", AssetSelection.key_substring("a")),
        ('key_substring:"*/a+"', AssetSelection.key_substring("*/a+")),
        ("not key:a", AssetSelection.all(include_sources=True) - AssetSelection.assets("a")),
        ("key:a and key:b", AssetSelection.assets("a") & AssetSelection.assets("b")),
        ("key:a or key:b", AssetSelection.assets("a") | AssetSelection.assets("b")),
        ("+key:a", AssetSelection.assets("a").upstream(1)),
        ("++key:a", AssetSelection.assets("a").upstream(2)),
        ("key:a+", AssetSelection.assets("a").downstream(1)),
        ("key:a++", AssetSelection.assets("a").downstream(2)),
        (
            "+key:a+",
            AssetSelection.assets("a").upstream(1) | AssetSelection.assets("a").downstream(1),
        ),
        ("*key:a", AssetSelection.assets("a").upstream()),
        ("key:a*", AssetSelection.assets("a").downstream()),
        (
            "*key:a*",
            AssetSelection.assets("a").downstream() | AssetSelection.assets("a").upstream(),
        ),
        (
            "key:a* and *key:b",
            AssetSelection.assets("a").downstream() & AssetSelection.assets("b").upstream(),
        ),
        (
            "*key:a and key:b* and *key:c*",
            AssetSelection.assets("a").upstream()
            & AssetSelection.assets("b").downstream()
            & (AssetSelection.assets("c").upstream() | AssetSelection.assets("c").downstream()),
        ),
        ("sinks(key:a)", AssetSelection.assets("a").sinks()),
        ("roots(key:c)", AssetSelection.assets("c").roots()),
        ("tag:foo", AssetSelection.tag("foo", "")),
        ("tag:foo=bar", AssetSelection.tag("foo", "bar")),
        ('owner:"owner@owner.com"', AssetSelection.owner("owner@owner.com")),
        ("group:my_group", AssetSelection.groups("my_group")),
        ("kind:my_kind", AssetSelection.tag(f"{KIND_PREFIX}my_kind", "")),
        (
            "code_location:my_location",
            CodeLocationAssetSelection(selected_code_location="my_location"),
        ),
    ],
)
def test_antlr_visit_basic(selection_str, expected_assets):
    # a -> b -> c
    @asset(tags={"foo": "bar"}, owners=["team:billing"])
    def a(): ...

    @asset(deps=[a], kinds={"python", "snowflake"})
    def b(): ...

    @asset(
        deps=[b],
        group_name="my_group",
    )
    def c(): ...

    assert (
        AntlrAssetSelectionParser(selection_str, include_sources=True).asset_selection
        == expected_assets
    )
