# Client Software Requirements — Telegram Appointment and Service Request Bot

**Brief ID:** DEMO-SRS-04  
**Target Git repository:** `telegram_business_bot`  
**Version:** 1.0 — 2026-11-14  

## 1. Client Background and Business Problem

A home appliance repair team takes inquiries through Telegram. Staff copy customer names, appliance types, addresses and preferred visiting windows into a spreadsheet manually. Requests are missed in busy periods and customers receive no reference number.

## 2. Requested Business Outcome

Customers submit structured repair requests via a Telegram bot; a dispatcher can review each request and update its status.

## 3. Expected Users

Authorized operators, administrators, and/or end customers as described in the functions below.

## 4. Functional Requirements

- **FR-01:** Offer Russian-language /start, help, service categories and a guided request form.
- **FR-02:** Collect appliance category, problem summary, district, preferred visit window and contact preference with user consent.
- **FR-03:** Validate required data and allow customers to review or cancel before submitting.
- **FR-04:** Assign each request a unique reference number and store it in the application database.
- **FR-05:** Notify a configured dispatcher chat of a new request without leaking bot credentials.
- **FR-06:** Provide dispatcher commands or a small panel to mark requests new, contacted, scheduled or closed.
- **FR-07:** Allow a customer to look up a request using its reference and authorized Telegram user identity.
- **FR-08:** Handle missing contact details, blocked bot conversations and Telegram API failures gracefully.
- **FR-09:** Supply a simulator to demonstrate end-to-end request processing without a live token.

## 5. Input Data and Expected Outputs

- Input: simulated customers submitting repair issues and live Telegram updates when configured.
- Output: request records, customer confirmation and dispatcher status updates.

## 6. Acceptance Tests / Definition of Done

- **AT-01:** Completing the guided form creates exactly one request and returns a reference number.
- **AT-02:** Dispatcher updates are persisted and shown in subsequent status checks.
- **AT-03:** A customer cannot access another customer’s request by guessing its reference.
- **AT-04:** Without a token, the local simulator can demonstrate submission, notification and closure.

## 7. Delivery Scope and Constraints

- **Suggested implementation:** Python/aiogram, SQLite. Official Telegram Bot API: https://core.telegram.org/bots/api
- Deliver a runnable application, complete source code, dependency files, sample configuration, automated tests, sample dataset, and real screenshots of the running application.
- Include a concise English README with setup, test, usage, and limitations; provide Russian end-user wording where the application is customer-facing.
- Operate as its own product with its own repository, data and configuration. It must never require any of the other nine portfolio projects.
- Avoid paid third-party services for the core demo; where a platform account or external credentials are required, provide a local simulator or clearly documented sample mode.
- Do not place secrets, confidential documents, genuine personal records, or copyrighted customer assets in the public repository.
- Deliver only the listed baseline features; production hosting, ongoing maintenance, advanced integrations, and additional scope require separate agreement.

## 8. Final Deliverables

1. Public-ready source repository named `telegram_business_bot`.
2. Runnable demonstration with synthetic or properly licensed sample data.
3. Installation and operating instructions, screenshots and automated tests.
4. Demonstration of all acceptance tests listed in Section 6.

## 9. Assumptions and Open Points

- The client scenarios and example volumes are illustrative and should be validated before real commercial development.
- UI layout, detailed database schema, security hardening, deployment targets and deadlines will be specified during technical design.
- Any expansion beyond the basic scope is subject to a new estimate and a revised requirements version.
