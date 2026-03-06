# Google reCAPTCHA Setup for KasuMarketplace

This document explains how to configure reCAPTCHA for production and what
is already implemented in the codebase.

## Frontend

- The `base.html` template loads the reCAPTCHA script from Google.
- All user-facing authentication forms (`login.html`, `signup_buyer.html`,
  `signup_vendor.html`) include a `<div class="g-recaptcha" ...>` widget.
  Each widget passes `data-callback="onRecaptchaSuccess"` and the
  submit button is disabled by default; a successful challenge enables it.

  ```html
  <div class="g-recaptcha" data-sitekey="{{ RECAPTCHA_PUBLIC_KEY }}" data-callback="onRecaptchaSuccess"></div>
  <button id="submitButton" type="submit" disabled>...</button>
  ```

- Social sign‑in buttons are outside the form so they bypass reCAPTCHA
  entirely.  This matches the requirement that social flows do not need a
  challenge.

## Backend

- `apps/users/forms.py` defines the `recaptcha` hidden field on signup and
  login forms.  Validation happens in each form's `clean()` method:
  - If `RECAPTCHA_PRIVATE_KEY` is set in settings, the token must be present
    and pass verification via Google's `siteverify` endpoint.
  - A helper `_validate_recaptcha()` performs the HTTP POST and logs the
    response for debugging.
  - During development or when using the Google test keys (`6LeIx...`), all
    tokens are treated as valid.

- The `apps/users/context_processors.recaptcha_keys` processor makes the site
  and secret keys available to templates (the secret key isn’t actually
  rendered, but the public key is).

- A dedicated test module (`apps/users/tests/test_recaptcha.py`) verifies:
  * Forms reject submissions without a token when a key is configured.
  * The validation helper is invoked and calls `requests.post`.
  * The login/signup pages render the widget and the disabled button.

## Settings

- Add your Google reCAPTCHA keys to your environment (e.g. `.env`):

  ```env
  RECAPTCHA_PUBLIC_KEY=your_site_key_here
  RECAPTCHA_PRIVATE_KEY=your_secret_key_here
  ```

  The repository includes the official Google test keys by default for
  convenience; they always return a successful verification.

- The application checks `settings.RECAPTCHA_PRIVATE_KEY` at runtime to
  determine whether to enforce the challenge.  You can leave it blank on a
  local dev machine if you don't want to deal with the widget.

## Deployment notes

- Make sure DNS and network allow outbound HTTPS to `www.google.com` so the
  verification request succeeds.  Failing to reach the API will cause all
  validation attempts to fail (users will see "reCAPTCHA validation
  failed.").

- Monitor `debug.log` for lines starting with `reCAPTCHA verify response:`
  to confirm the remote service is being contacted.
