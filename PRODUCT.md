# Product

## Register

product

## Users

Accountants, warehouse managers, and department heads at companies running JustClick ERP. They query financial transactions, inventory reports, customer balances, and employee data. Most are Arabic-speaking, working on desktop during business hours in well-lit offices. They are not technical users; they want answers in their language without writing SQL.

## Product Purpose

A conversational interface that turns natural-language questions (Arabic or English) into live Oracle SQL queries against JustClick ERP data. Success: a user types a question and gets a formatted, trustworthy answer within seconds, with the option to inspect the generated SQL.

## Brand Personality

Professional, intelligent, minimal. The interface should feel like a sharp internal tool built by a team that respects its users' time. No toy-like flourishes, no gimmicks. Confident but quiet.

## Anti-references

- Generic free chat templates (Bootstrap chat UIs, identical dark-gradient chatbots)
- ChatGPT clones (centered input, OpenAI layout, "how can I help you today" empty states)
- Overly playful or consumer chatbot aesthetics (bubble animations, cartoon avatars, confetti)
- SaaS marketing landing pages disguised as product UI

## Design Principles

1. **Answer first**: the data answer is the hero, not the interface chrome
2. **Earn trust**: show the SQL, show row counts, show timestamps; transparency builds confidence
3. **Respect the workflow**: users are mid-task in their ERP; the chatbot is a tool, not a destination
4. **Arabic-native**: RTL is not an afterthought; the layout, spacing, and typography are designed for Arabic first
5. **Stay out of the way**: minimal UI surface, maximum data clarity

## Accessibility & Inclusion

- WCAG 2.1 AA minimum
- High contrast text on all surfaces
- Keyboard navigable (Tab, Enter, Escape)
- Reduced motion respected via prefers-reduced-motion
- RTL-first layout with graceful LTR fallback for SQL blocks and English content
