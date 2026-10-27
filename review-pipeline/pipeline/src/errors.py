# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
"""Project exceptions.

`UserFacingError` marks errors whose message was written by this project and
is safe to show to a caller (a bad config.json value, a malformed request, a
review missing a required field). Any other exception may carry AWS request
details (bucket names, ARNs), so the API layer logs it in full and returns only
a generic message plus a request id.

This module depends on nothing else in the project, so every layer may import it.
"""

from __future__ import annotations


class UserFacingError(Exception):
    """An error with a message that is safe to return to the caller."""


class InvalidRequestError(UserFacingError):
    """The request itself is malformed (for example a body that is not JSON)."""


class InvalidInputError(UserFacingError, ValueError):
    """An input review is missing a required field or has a bad value."""


class InvalidConfigError(UserFacingError, ValueError):
    """config.json holds a value the pipeline cannot use."""
