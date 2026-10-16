# Hub worktrees

Only main, hub and ml slots belong to this repository. Client applications have separate repositories and deployment stacks.
Existing single-stack testing policy remains: code-only worktrees by default, Docker tests in the designated test stack. These changes do not start any containers.

Use create.sh hub or create.sh ml for code worktrees; slots.sh lists only Hub/PostgreSQL/Redis/ML ports.
Old client worktrees must be archived or migrated manually; no running services, volumes or existing worktrees were deleted by this source change.
