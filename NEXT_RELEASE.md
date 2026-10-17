# Next release (not released yet)
Changes waiting for the next version. When releasing, bump APP_VERSION and move these into release-notes/<version>.md.

* **Fixed:** recording could freeze on one frame (with no sound) partway through a game, so clips showed a still picture and never played. The app now notices within 8 seconds and restarts recording by itself.
