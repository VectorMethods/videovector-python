# Public Repository Governance

This public repository is maintained through organization automation.

## Identity Policy

- Public commits, release tags, and generated release notes must use
  `VectorMethods Engineering <opensource@vectormethods.com>`.
- Do not push commits, create tags, merge pull requests, or publish releases
  from a personal account or personal workstation.
- Do not add `Co-authored-by`, `Signed-off-by`, or similar trailers that reveal
  individual contributor names, emails, handles, or local machine identities.

## Change Flow

1. Develop and review changes in private company repositories or branches.
2. Sync approved public changes through the organization automation identity.
3. Run CI on the public repository before merging to `main`.
4. Publish releases only through `.github/workflows/release.yml`.

If an emergency manual intervention is unavoidable, rewrite and verify the
history before pushing to public refs. The verification must scan author and
committer metadata, commit messages, tags, and all reachable blobs for personal
names, emails, account handles, and local hostnames.
