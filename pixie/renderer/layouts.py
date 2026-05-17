"""Layout selector.

Maps ``tool.layout`` (``form``, ``chat``, ``split``) to the
appropriate top-level template. ``form`` is the default left-inputs /
right-outputs view; ``chat`` is a message column plus right rail;
``split`` is single-column interleaved.
"""

from __future__ import annotations

# TODO(phase-4b): implement layout_for(tool) -> str template name.
