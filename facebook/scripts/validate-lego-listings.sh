#!/usr/bin/env bash
# Validate lego-finder agent JSON output against the expected schema.
# Usage: validate-lego-listings.sh <json-file>
# Returns: JSON {"valid": true} or {"valid": false, "issues": [...]}
# Exit code: 0 if valid, 1 if invalid or error

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo '{"valid": false, "issues": ["Usage: validate-lego-listings.sh <json-file>"]}'
    exit 1
fi

JSON_FILE="$1"

if [[ ! -f "$JSON_FILE" ]]; then
    echo "{\"valid\": false, \"issues\": [\"File not found: $JSON_FILE\"]}"
    exit 1
fi

# Validate JSON syntax first
if ! jq empty "$JSON_FILE" 2>/dev/null; then
    echo '{"valid": false, "issues": ["Invalid JSON syntax"]}'
    exit 1
fi

# Collect all issues
ISSUES=$(jq -r '
def collect_issues:
  . as $root |
  [] |

  # Check top-level structure
  (if ($root | type) != "object" then . + ["Root must be a JSON object"] else . end) |
  (if ($root | has("search") | not) then . + ["Missing top-level \"search\" block"] else . end) |
  (if ($root | has("listings") | not) then . + ["Missing top-level \"listings\" array"] else . end) |

  # Validate search block
  (if ($root | has("search")) then
    (if ($root.search | has("query") | not) then . + ["search: missing \"query\""] else . end) |
    (if ($root.search | has("location") | not) then . + ["search: missing \"location\""] else . end) |
    (if ($root.search | has("total_listings_found") | not) then . + ["search: missing \"total_listings_found\""] else . end) |
    (if ($root.search | has("listings_returned") | not) then . + ["search: missing \"listings_returned\""] else . end)
  else . end) |

  # Validate listings array
  (if ($root | has("listings")) then
    (if ($root.listings | type) != "array" then
      . + ["\"listings\" must be an array"]
    else
      # Check each listing
      reduce range($root.listings | length) as $i (.;
        ($root.listings[$i]) as $item |

        # Required fields for all types
        (if ($item | has("type") | not) then . + ["listings[\($i)]: missing \"type\""] else . end) |
        (if ($item | has("listing_title") | not) then . + ["listings[\($i)]: missing \"listing_title\""] else . end) |
        (if ($item | has("listing_url") | not) then . + ["listings[\($i)]: missing \"listing_url\""] else . end) |
        (if ($item | has("location") | not) then . + ["listings[\($i)]: missing \"location\""] else . end) |
        (if ($item | has("total_price") | not) then . + ["listings[\($i)]: missing \"total_price\""] else . end) |
        (if ($item | has("images") | not) then . + ["listings[\($i)]: missing \"images\""] else . end) |

        # Validate total_price is numeric
        (if ($item | has("total_price")) and (($item.total_price | type) != "number") and ($item.total_price != null) then
          . + ["listings[\($i)]: \"total_price\" must be numeric, got \($item.total_price | type)"]
        else . end) |

        # Validate listing_url starts with https://www.facebook.com
        (if ($item | has("listing_url")) and (($item.listing_url | type) == "string") and (($item.listing_url | startswith("https://www.facebook.com")) | not) then
          . + ["listings[\($i)]: \"listing_url\" must start with https://www.facebook.com"]
        else . end) |

        # Type-specific validations
        (if $item.type == "lego_set" then
          (if ($item | has("sets") | not) then
            . + ["listings[\($i)]: lego_set missing \"sets\" array"]
          elif ($item.sets | type) != "array" then
            . + ["listings[\($i)]: \"sets\" must be an array"]
          elif ($item.sets | length) == 0 then
            . + ["listings[\($i)]: \"sets\" array must not be empty"]
          else . end)
        elif $item.type == "bulk" then
          (if ($item | has("estimated_pounds") | not) then
            . + ["listings[\($i)]: bulk missing \"estimated_pounds\" field"]
          else . end) |
          (if ($item | has("price_per_pound") | not) then
            . + ["listings[\($i)]: bulk missing \"price_per_pound\" field"]
          else . end)
        elif $item.type == "unknown" then
          .
        elif ($item | has("type")) then
          . + ["listings[\($i)]: invalid type \"\($item.type)\", must be lego_set, bulk, or unknown"]
        else . end)
      )
    end)
  else . end);

collect_issues |
if length == 0 then
  {"valid": true}
else
  {"valid": false, "issues": .}
end
' "$JSON_FILE")

echo "$ISSUES"

# Exit based on validity
if echo "$ISSUES" | jq -e '.valid' > /dev/null 2>&1; then
    exit 0
else
    exit 1
fi
