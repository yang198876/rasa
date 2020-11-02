from typing import Any, Optional, Tuple, Text, Dict, Set, List

import typing
import copy

import rasa.shared.utils.io
from rasa.shared.exceptions import RasaException
from rasa.shared.nlu.constants import (
    TEXT,
    INTENT,
    RESPONSE,
    INTENT_RESPONSE_KEY,
    METADATA,
    METADATA_INTENT,
    METADATA_EXAMPLE,
    ENTITIES,
    RESPONSE_IDENTIFIER_DELIMITER,
    FEATURE_TYPE_SENTENCE,
    FEATURE_TYPE_SEQUENCE,
    ACTION_TEXT,
    ACTION_NAME,
)

if typing.TYPE_CHECKING:
    from rasa.shared.nlu.training_data.features import Features


class Message:
    def __init__(
        self,
        data: Optional[Dict[Text, Any]] = None,
        output_properties: Optional[Set] = None,
        time: Optional[Text] = None,
        features: Optional[List["Features"]] = None,
        **kwargs: Any,
    ) -> None:
        self.time = time
        self.data = data.copy() if data else {}
        self.features = features if features else []

        self.data.update(**kwargs)

        if output_properties:
            self.output_properties = output_properties
        else:
            self.output_properties = set()
        self.output_properties.add(TEXT)

    def add_features(self, features: Optional["Features"]) -> None:
        if features is not None:
            self.features.append(features)

    def set(self, prop, info, add_to_output=False) -> None:
        self.data[prop] = info
        if add_to_output:
            self.output_properties.add(prop)

    def get(self, prop, default=None) -> Any:
        return self.data.get(prop, default)

    def as_dict_nlu(self) -> dict:
        """Get dict representation of message as it would appear in training data"""

        d = self.as_dict()
        if d.get(INTENT, None):
            d[INTENT] = self.get_full_intent()
        d.pop(RESPONSE, None)
        d.pop(INTENT_RESPONSE_KEY, None)
        return d

    def as_dict(self, only_output_properties=False) -> dict:
        if only_output_properties:
            d = {
                key: value
                for key, value in self.data.items()
                if key in self.output_properties
            }
        else:
            d = self.data

        # Filter all keys with None value. These could have come while building the
        # Message object in markdown format
        return {key: value for key, value in d.items() if value is not None}

    def __eq__(self, other) -> bool:
        if not isinstance(other, Message):
            return False
        else:
            return ordered(other.data) == ordered(self.data)

    def __hash__(self) -> int:
        return hash(str(ordered(self.data)))

    @classmethod
    def build(
        cls,
        text: Text,
        intent: Optional[Text] = None,
        entities: Optional[List[Dict[Text, Any]]] = None,
        intent_metadata: Optional[Any] = None,
        example_metadata: Optional[Any] = None,
        **kwargs: Any,
    ) -> "Message":
        """
        Build a Message from `UserUttered` data.
        Args:
            text: text of a user's utterance
            intent: an intent of the user utterance
            entities: entities in the user's utterance
            intent_metadata: optional metadata for the intent
            example_metadata: optional metadata for the intent example
        Returns:
            Message
        """
        data: Dict[Text, Any] = {TEXT: text}
        if intent:
            split_intent, response_key = cls.separate_intent_response_key(intent)
            if split_intent:
                data[INTENT] = split_intent
            if response_key:
                # intent label can be of the form - {intent}/{response_key},
                # so store the full intent label in intent_response_key
                data[INTENT_RESPONSE_KEY] = intent
        if entities:
            data[ENTITIES] = entities
        if intent_metadata is not None:
            data[METADATA] = {METADATA_INTENT: intent_metadata}
        if example_metadata is not None:
            data.setdefault(METADATA, {})[METADATA_EXAMPLE] = example_metadata

        return cls(data, **kwargs)

    def get_full_intent(self) -> Text:
        """Get intent as it appears in training data"""

        return (
            self.get(INTENT_RESPONSE_KEY)
            if self.get(INTENT_RESPONSE_KEY)
            else self.get(INTENT)
        )

    def get_combined_intent_response_key(self) -> Text:
        """Get intent as it appears in training data"""

        rasa.shared.utils.io.raise_warning(
            "`get_combined_intent_response_key` is deprecated and "
            "will be removed in future versions. "
            "Please use `get_full_intent` instead.",
            category=DeprecationWarning,
        )
        return self.get_full_intent()

    @staticmethod
    def separate_intent_response_key(
        original_intent: Text,
    ) -> Tuple[Text, Optional[Text]]:

        split_title = original_intent.split(RESPONSE_IDENTIFIER_DELIMITER)
        if len(split_title) == 2:
            return split_title[0], split_title[1]
        elif len(split_title) == 1:
            return split_title[0], None

        raise RasaException(
            f"Intent name '{original_intent}' is invalid, "
            f"it cannot contain more than one '{RESPONSE_IDENTIFIER_DELIMITER}'."
        )

    def get_sparse_features(
        self, attribute: Text, featurizers: Optional[List[Text]] = None
    ) -> Tuple[Optional["Features"], Optional["Features"]]:
        """Get all sparse features for the given attribute that are coming from the
        given list of featurizers.
        If no featurizers are provided, all available features will be considered.
        Args:
            attribute: message attribute
            featurizers: names of featurizers to consider
        Returns:
            Sparse features.
        """
        if featurizers is None:
            featurizers = []

        sequence_features, sentence_features = self._filter_sparse_features(
            attribute, featurizers
        )

        sequence_features = self._combine_features(sequence_features, featurizers)
        sentence_features = self._combine_features(sentence_features, featurizers)

        return sequence_features, sentence_features

    def get_dense_features(
        self, attribute: Text, featurizers: Optional[List[Text]] = None
    ) -> Tuple[Optional["Features"], Optional["Features"]]:
        """Get all dense features for the given attribute that are coming from the given
        list of featurizers.
        If no featurizers are provided, all available features will be considered.
        Args:
            attribute: message attribute
            featurizers: names of featurizers to consider
        Returns:
            Dense features.
        """
        if featurizers is None:
            featurizers = []

        sequence_features, sentence_features = self._filter_dense_features(
            attribute, featurizers
        )

        sequence_features = self._combine_features(sequence_features, featurizers)
        sentence_features = self._combine_features(sentence_features, featurizers)

        return sequence_features, sentence_features

    def features_present(
        self, attribute: Text, featurizers: Optional[List[Text]] = None
    ) -> bool:
        """Check if there are any features present for the given attribute and
        featurizers.
        If no featurizers are provided, all available features will be considered.
        Args:
            attribute: message attribute
            featurizers: names of featurizers to consider
        Returns:
            ``True``, if features are present, ``False`` otherwise
        """
        if featurizers is None:
            featurizers = []

        (
            sequence_sparse_features,
            sentence_sparse_features,
        ) = self._filter_sparse_features(attribute, featurizers)
        sequence_dense_features, sentence_dense_features = self._filter_dense_features(
            attribute, featurizers
        )

        return (
            len(sequence_sparse_features) > 0
            or len(sentence_sparse_features) > 0
            or len(sequence_dense_features) > 0
            or len(sentence_dense_features) > 0
        )

    def _filter_dense_features(
        self, attribute: Text, featurizers: List[Text]
    ) -> Tuple[List["Features"], List["Features"]]:
        sentence_features = [
            f
            for f in self.features
            if f.attribute == attribute
            and f.is_dense()
            and f.type == FEATURE_TYPE_SENTENCE
            and (f.origin in featurizers or not featurizers)
        ]
        sequence_features = [
            f
            for f in self.features
            if f.attribute == attribute
            and f.is_dense()
            and f.type == FEATURE_TYPE_SEQUENCE
            and (f.origin in featurizers or not featurizers)
        ]
        return sequence_features, sentence_features

    def _filter_sparse_features(
        self, attribute: Text, featurizers: List[Text]
    ) -> Tuple[List["Features"], List["Features"]]:
        sentence_features = [
            f
            for f in self.features
            if f.attribute == attribute
            and f.is_sparse()
            and f.type == FEATURE_TYPE_SENTENCE
            and (f.origin in featurizers or not featurizers)
        ]
        sequence_features = [
            f
            for f in self.features
            if f.attribute == attribute
            and f.is_sparse()
            and f.type == FEATURE_TYPE_SEQUENCE
            and (f.origin in featurizers or not featurizers)
        ]

        return sequence_features, sentence_features

    @staticmethod
    def _combine_features(
        features: List["Features"], featurizers: Optional[List[Text]] = None
    ) -> Optional["Features"]:
        combined_features = None

        for f in features:
            if combined_features is None:
                combined_features = copy.deepcopy(f)
                combined_features.origin = featurizers
            else:
                combined_features.combine_with_features(f)

        return combined_features

    def is_core_message(self) -> bool:
        """Checks whether the message is a core message or not.

        E.g. a core message is created from a story, not from the NLU data.

        Returns:
            True, if message is a core message, false otherwise.
        """
        return bool(
            self.data.get(ACTION_NAME)
            or self.data.get(ACTION_TEXT)
            or (
                (self.data.get(INTENT) or self.data.get(RESPONSE))
                and not self.data.get(TEXT)
            )
            or (
                self.data.get(TEXT)
                and not (self.data.get(INTENT) or self.data.get(RESPONSE))
            )
        )


def ordered(obj: Any) -> Any:
    if isinstance(obj, dict):
        return sorted((k, ordered(v)) for k, v in obj.items())
    if isinstance(obj, list):
        return sorted(ordered(x) for x in obj)
    else:
        return obj
