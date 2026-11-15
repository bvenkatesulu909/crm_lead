### Agent evaluation: deepseek (dataset 0717e3a15da5)

| Agent | Cases | Passed | Failed |
|---|---:|---:|---:|
| account_research | 6 | 4 | 2 |
| deal_desk | 7 | 4 | 3 |
| **All** | 13 | 8 | 5 |

Forbidden-tool violations: 0 - answers claiming a change was done: 0 - tool precision: n/a - recall: n/a - argument accuracy: n/a

**Failed cases:** desk-brief-without-tasks, desk-manager-reviews-a-colleagues-deal, desk-two-tasks-wait-for-approval, research-cited-brief, research-support-reads-any-account
- `desk-brief-without-tasks` - outcome: expected 'answered', got 'proposal_pending'
- `desk-brief-without-tasks` - proposals: 2 proposal(s) stored, expected 0
- `desk-manager-reviews-a-colleagues-deal` - proposals: 2 proposal(s) stored, expected 1; subject: expected 'Ask the owner about the close date', got 'Reset close date and log a concrete next step with a named primary contact'
- `desk-two-tasks-wait-for-approval` - proposals: subject: expected 'Agree a new close date', got 'Confirm a new close date or close out the deal'; due_in_days: expected 2, got 3; subject: expected 'Send a quote', got 'Produce a quote for the 8.5M INR deal'; due_in_days: expected 5, got 14
- `research-cited-brief` - brief_sentences: 7 sentence(s) kept, expected 2
- `research-support-reads-any-account` - brief_sentences: 5 sentence(s) kept, expected 1

