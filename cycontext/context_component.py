"""The ConTextComponent definiton."""
from os import path

# Filepath to default rules which are included in package
from pathlib import Path

from spacy.matcher import Matcher, PhraseMatcher
from spacy.tokens import Doc, Span

from .tag_object import TagObject
from .context_graph import ConTextGraph
from .context_item import ConTextItem

#
DEFAULT_ATTRS = {
    "NEGATED_EXISTENCE": {"is_negated": True},
    "POSSIBLE_EXISTENCE": {"is_uncertain": True},
    "HISTORICAL": {"is_historical": True},
    "HYPOTHETICAL": {"is_hypothetical": True},
    "FAMILY": {"is_family": True},
}

DEFAULT_RULES_FILEPATH = path.join(
    Path(__file__).resolve().parents[1], "kb", "default_rules.json"
)


class ConTextComponent:
    """The ConTextComponent for spaCy processing."""

    name = "context"

    def __init__(
        self,
        nlp,
        targets="ents",
        add_attrs=True,
        prune=True,
        remove_overlapping_modifiers=False,
        rules="default",
        rule_list=None,
        allowed_types=None,
        excluded_types=None,
        max_targets=None,
        max_scope=None,
    ):

        """Create a new ConTextComponent algorithm.

        This component matches modifiers in a Doc,
        defines their scope, and identifies edges between targets and modifiers.
        Sets two spaCy extensions:
            - Span._.modifiers: a list of TagObject objects which modify a target Span
            - Doc._.context_graph: a ConText graph object which contains the targets,
                modifiers, and edges between them.

        Args:
            nlp: a spaCy NLP model
            targets: the attribute of Doc which contains targets.
                Default is "ents", in which case it will use the standard Doc.ents attribute.
                Otherwise will look for a custom attribute in Doc._.{targets}
            add_attrs: Whether or not to add the additional spaCy Span attributes (ie., Span._.x)
                defining assertion on the targets. By default, these are:
                - is_negated: True if a target is modified by 'NEGATED_EXISTENCE', default False
                - is_uncertain: True if a target is modified by 'POSSIBLE_EXISTENCE', default False
                - is_historical: True if a target is modified by 'HISTORICAL', default False
                - is_hypothetical: True if a target is modified by 'HYPOTHETICAL', default False
                - is_family: True if a target is modified by 'FAMILY', default False
                In the future, these should be made customizable.
            prune: Whether or not to prune modifiers which are substrings of another modifier.
                For example, if "no history of" and "history of" are both ConTextItems, both will match
                the text "no history of afib", but only "no history of" should modify afib.
                If True, will drop shorter substrings completely.
                Default True.
            remove_overlapping_modifiers: Whether or not to remove any matched modifiers which overlap
                with target entities. If False, any overlapping modifiers will not modify the overlapping
                entity but will still modify any other targets in its scope.
                Default False.
            rules: Which rules to load on initialization. Default is 'default'.
                - 'default': Load the default set of rules provided with cyConText
                - 'other': Load a custom set of rules, please also set rule_list with a file path or list.
                - None: Load no rules.
            rule_list: The location of rules in json format or a list of ContextItems. Default
                is None.
            allowed_types (set or None): A set of target labels to allow a ConTextItem to modify.
                If None, will apply to any type not specifically excluded in excluded_types.
                Only one of allowed_types and excluded_types can be used. An error will be thrown
                if both or not None.
                If this attribute is also defined in the ConTextItem, it will keep that value.
                Otherwise it will inherit this value.
            excluded_types (set or None): A set of target labels which this modifier cannot modify.
                If None, will apply to all target types unless allowed_types is not None.
                If this attribute is also defined in the ConTextItem, it will keep that value.
                Otherwise it will inherit this value.
            max_targets (int or None): The maximum number of targets which a modifier can modify.
                If None, will modify all targets in its scope.
                If this attribute is also defined in the ConTextItem, it will keep that value.
                Otherwise it will inherit this value.
            max_scope (int or None): A number to explicitly limit the size of the modifier's scope
                If this attribute is also defined in the ConTextItem, it will keep that value.
                Otherwise it will inherit this value.


        Returns:
            context: a ConTextComponent

        Raises:
            ValueError: if one of the parameters is incorrectly formatted.
        """

        self.nlp = nlp
        if targets != "ents":
            raise NotImplementedError()
        self._target_attr = targets
        self.prune = prune
        self.remove_overlapping_modifiers = remove_overlapping_modifiers

        self._item_data = []
        self._i = 0
        self._categories = set()

        # _modifier_item_mapping: A mapping from spaCy Matcher match_ids to ConTextItem
        # This allows us to use spaCy Matchers while still linking back to the ConTextItem
        # To get the rule and category
        self._modifier_item_mapping = dict()
        self.phrase_matcher = PhraseMatcher(
            nlp.vocab, attr="LOWER", validate=True
        )  # TODO: match on custom attributes
        self.matcher = Matcher(nlp.vocab, validate=True)

        self.register_graph_attributes()
        if add_attrs is False:
            self.add_attrs = False
        elif add_attrs is True:
            self.add_attrs = True
            self.context_attributes_mapping = DEFAULT_ATTRS
            self.register_default_attributes()
        elif isinstance(add_attrs, dict):
            # Check that each of the attributes being added has been set
            for modifier in add_attrs.keys():
                attr_dict = add_attrs[modifier]
                for attr_name, attr_value in attr_dict.items():
                    if not Span.has_extension(attr_name):
                        raise ValueError(
                            "Custom extension {0} has not been set. Call Span.set_extension."
                        )

            self.add_attrs = True
            self.context_attributes_mapping = add_attrs

        else:
            raise ValueError(
                "add_attrs must be either True (default), False, or a dictionary, not {0}".format(
                    add_attrs
                )
            )

        self.allowed_types = allowed_types
        self.excluded_types = excluded_types
        self.max_targets = max_targets
        self.max_scope = max_scope

        if rules == "default":

            item_data = ConTextItem.from_json(DEFAULT_RULES_FILEPATH)
            self.add(item_data)

        elif rules == "other":
            # use custom rules
            if isinstance(rule_list, str):
                # if rules_list is a string, then it must be a path to a json
                if "yaml" in rule_list or "yml" in rule_list:
                    try:
                        item_data = ConTextItem.from_yaml(rule_list)
                    except:
                        raise ValueError(
                            "rule list {0} could not be read".format(rule_list)
                        )
                elif path.exists(rule_list):
                    item_data = ConTextItem.from_json(rule_list)
                    self.add(item_data)
                else:
                    raise ValueError(
                        "rule_list must be a valid path. Currently is: {0}".format(
                            rule_list
                        )
                    )

            elif isinstance(rule_list, list):
                # otherwise it is a list of contextitems
                if not rule_list:
                    raise ValueError("rule_list must not be empty.")
                for item in rule_list:
                    # check that all items are contextitems
                    if not isinstance(item, ConTextItem):
                        raise ValueError(
                            "rule_list must contain only ContextItems. Currently contains: {0}".format(
                                type(item)
                            )
                        )
                self.add(rule_list)

            else:
                raise ValueError(
                    "rule_list must be a valid path or list of ContextItems. Currenty is: {0}".format(
                        type(rule_list)
                    )
                )

        elif not rules:
            # otherwise leave the list empty.
            # do nothing
            self._item_data = []

        else:
            # loading from json path or list is possible later
            raise ValueError(
                "rules must either be 'default' (default), 'other' or None."
            )

    @property
    def item_data(self):
        """Returns list of ConTextItems"""
        return self._item_data

    @property
    def categories(self):
        """Returns list of categories from ConTextItems"""
        return self._categories

    def add(self, item_data):
        """Add a list of ConTextItem items to ConText.

        Args:
            item_data: a list of ConTextItems to add.

        Raises:
            TypeError: if item_data contains an object that is not a ConTextItem.
        """
        try:
            self._item_data += item_data
        except TypeError:
            raise TypeError(
                "item_data must be a list of ConText items. If you're just passing in a single ConText Item, "
                "make sure to wrap the item in a list: `context.add([item])`"
            )

        for item in item_data:

            # UID is the hash which we'll use to retrieve the ConTextItem from a spaCy match
            # And will be a key in self._modifier_item_mapping
            uid = self.nlp.vocab.strings[str(self._i)]
            # If no pattern is defined,
            # match on the literal phrase.
            if item.pattern is None:
                self.phrase_matcher.add(
                    str(self._i),
                    [self.nlp.make_doc(item.literal)],
                    on_match=item.on_match,
                )
            else:

                self.matcher.add(str(self._i), [item.pattern], on_match=item.on_match)
            self._modifier_item_mapping[uid] = item
            self._i += 1
            self._categories.add(item.category)

            # If global attributes like allowed_types and max_scope are defined,
            # check if the ConTextItem has them defined. If not, set to the global
            for attr in ("allowed_types", "excluded_types", "max_scope", "max_targets"):
                value = getattr(self, attr)
                if value is None:  # No global value set
                    continue
                if (
                    getattr(item, attr) is None
                ):  # If the item itself has it defined, don't override
                    setattr(item, attr, value)

    def register_default_attributes(self):
        """Register the default values for the Span attributes defined in DEFAULT_ATTRS."""
        for attr_name in [
            "is_negated",
            "is_uncertain",
            "is_historical",
            "is_hypothetical",
            "is_family",
        ]:
            try:
                Span.set_extension(attr_name, default=False)
            except ValueError:  # Extension already set
                pass

    def register_graph_attributes(self):
        """Register spaCy container custom attribute extensions.

        By default will register Span._.modifiers and Doc._.context_graph.

        If self.add_attrs is True, will add additional attributes to span
            as defined in DEFAULT_ATTRS:
            - is_negated
            - is_historical
            - is_experiencer
        """
        Span.set_extension("modifiers", default=(), force=True)
        Doc.set_extension("context_graph", default=None, force=True)

    def set_context_attributes(self, edges):
        """Add Span-level attributes to targets with modifiers.

        Args:
            edges: the edges to modify

        """

        for (target, modifier) in edges:
            if modifier.category in self.context_attributes_mapping:
                attr_dict = self.context_attributes_mapping[modifier.category]
                for attr_name, attr_value in attr_dict.items():
                    setattr(target._, attr_name, attr_value)

    def __call__(self, doc):
        """Applies the ConText algorithm to a Doc.

        Args:
            doc: a spaCy Doc

        Returns:
            doc: a spaCy Doc
        """
        if self._target_attr == "ents":
            targets = doc.ents
        else:
            targets = getattr(doc._, self._target_attr)

        # Store data in ConTextGraph object
        # TODO: move some of this over to ConTextGraph
        context_graph = ConTextGraph(
            remove_overlapping_modifiers=self.remove_overlapping_modifiers
        )

        context_graph.targets = targets

        context_graph.modifiers = []

        matches = self.phrase_matcher(doc)
        matches += self.matcher(doc)

        # Sort matches
        matches = sorted(matches, key=lambda x: x[1])
        for (match_id, start, end) in matches:
            # Get the ConTextItem object defining this modifier
            item_data = self._modifier_item_mapping[match_id]
            tag_object = TagObject(item_data, start, end, doc)
            context_graph.modifiers.append(tag_object)

        if self.prune:
            context_graph.prune_modifiers()
        context_graph.update_scopes()
        context_graph.apply_modifiers()

        # Link targets to their modifiers
        for target, modifier in context_graph.edges:
            target._.modifiers += (modifier,)

        # If add_attrs is True, add is_negated, is_current, is_asserted to targets
        if self.add_attrs:
            self.set_context_attributes(context_graph.edges)

        doc._.context_graph = context_graph

        return doc
