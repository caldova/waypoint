# Seller environment setup and teardown

Use **Actions -> Set up seller repository** to create a repository the seller
administers. The workflow prefers GitHub's template path when
`caldova/waypoint` is marked as a template; otherwise it creates an explicit
GitHub fork and reports that fork relationship. It requires the
`SELLER_REPO_ADMIN_TOKEN` secret and verifies `ADMIN` permission before invoking
the existing Azure OIDC bootstrap.

Use **Actions -> Teardown seller environment** with the exact subscription,
application resource group, state resource group, and azd environment. The
default is a sanitized dry-run plan. To delete, turn off `dry_run` and type the
azd environment name exactly. App registrations remain by default and require
the separate `delete_app_registrations` flag.

Teardown only considers app registrations recorded in the named state/azd
environment or tagged for that environment. It additionally requires the
deployment service principal to be an owner and never selects an application by
display name. The application resource group is deleted first. Any failure
before state deletion preserves the state resource group and local azd state.
