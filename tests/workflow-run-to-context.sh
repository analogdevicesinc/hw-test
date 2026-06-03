#!/bin/bash
set -xeuo pipefail

json="$(dirname -- "${BASH_SOURCE[0]}" )/sample/workflow-run.completed.json"
get() { jq -r "$1" "$json"; }

# workflow dispatch inputs
org=$(get '.workflow_run.repository.owner.login')
repository=$(get '.workflow_run.repository.name')
head_sha=$(get '.workflow_run.head_sha')
is_fork=$(get '.workflow_run.head_repository.fork')
pr_number=$(get '.workflow_run.pull_requests[0].number // empty')

if [[ "$is_fork" == "true" ]]; then
  pr_number=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
    "https://api.github.com/search/issues?q=repo:$org/$repository+is:pr+sha:$head_sha" | jq -r '.items[0].number // empty')
  [[ -n "$pr_number" ]] || { echo "::error ::Pull request for sha ${head_sha} not found" ; exit 1 ; }
fi
pr_json=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$org/$repository/pulls/$pr_number")
base_branch_head_sha=$(echo "$pr_json" | jq -r '.base.sha')
changed_files=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$org/$repository/pulls/$pr_number/files" | jq -r '.[].filename')
base_sha=$(curl -s -H "Authorization: Bearer $GITHUB_TOKEN" \
  "https://api.github.com/repos/$org/$repository/compare/${base_branch_head_sha}...${head_sha}" | jq -r '.merge_base_commit.sha')
pr_state=$(echo "$pr_json" | jq -r '.state')

merge_commit_sha=$(echo "$pr_json" | jq -r '.merge_commit_sha // empty')

out=$(mktemp)

# action outputs
{
  echo "head_sha=$head_sha"
  echo "base_sha=$base_sha"
  echo "merge_commit_sha=$merge_commit_sha" # empty is conflict
  echo "pr_number=$pr_number"
  echo "state=$pr_state"
  echo "changed_files="
  echo "$changed_files"
  echo "base_branch_head_sha=$base_branch_head_sha"
} > "$out"

echo "$out"
cat "$out"
