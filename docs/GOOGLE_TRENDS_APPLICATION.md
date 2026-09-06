# Google Trends alpha application draft

Status: prepared for owner review; not filled or submitted. Checked 6 September 2026.

[Official API page](https://developers.google.com/search/apis/trends) · [Application form](https://docs.google.com/forms/d/e/1FAIpQLSfiP3XUUWGr4CkYk1oJHpthCAcAw2kL0UaE6p7tq3ZoxFiLtA/viewform)

## Owner-supplied details still needed

The form requires every answer. Supply these privately, outside the public repository:

- Given and family names.
- Contact email, requested by the form as an organization address.
- Gmail identity to receive access, plus permission to use its email with the response.
- An existing Google Cloud project ID accessible to that Gmail identity.
- A calendar date when implementation can begin.
- Availability to provide feedback by email, video meeting, or both.

Proposed project answers, to use only if they accurately describe the owner's intended use:

- Project website: <https://acuestamd.github.io/project-geosentinel/>
- Applicant category: independent developer.
- Purpose category: noncommercial experimental work.

Do not claim an institutional position, affiliation, research approval, Google endorsement, or WHO endorsement. Do not create a Cloud project, enable billing, or change access merely to complete this draft.

## Proposed use-case response

GeoSentinel is an independently operated, open-source prototype for organizing public infectious-disease reports and inspecting environmental context. The public application is at https://acuestamd.github.io/project-geosentinel/ and its source is at https://github.com/acuestamd/project-geosentinel.

We would like to test whether aggregated Google search interest adds useful information to a narrowly scoped dengue forecasting experiment in Rio de Janeiro, Brazil. The target is weekly reported dengue case counts at two- and four-week horizons, not individual health status or clinical severity. Search data would be an optional covariate alongside official epidemiological time series and local weather, rather than a substitute for surveillance.

The experiment would use weekly data over the available historical window, starting with a small, predefined set of Portuguese disease and symptom queries. We would align the geographic unit to the API's supported coverage. State-level search interest would remain explicitly labeled as a state-level contextual feature if the epidemiological target is municipal; it would never be presented as measured city-level search activity. We would document sampling, scaling, suppression, missingness, retrieval time, query definitions, and changes in coverage.

We plan to compare simple persistence and seasonal baselines with models using cases alone, cases plus weather, and cases plus weather plus search interest. Evaluation would use rolling historical forecast dates, preserve data-availability timestamps, and measure forecast error, interval coverage, and calibration. Retrospective experiments without historical data vintages would be labeled accordingly. Changes in media attention and search behavior would be treated as potential confounders. Search interest would be retained only if its incremental value is supported out of sample.

The alpha integration would run in a separate test environment. The existing public dashboard would continue operating without depending on alpha availability. We would examine permitted publication and redistribution before exposing any search-derived output. No individual search histories, identities, or personal health information would be requested, inferred, or published.

Implementation feedback could cover geographic coverage, consistent scaling across requests, weekly alignment, reproducibility, revised values, rate limits, missing results, and error handling. We would provide reproducible technical examples through the feedback channel selected by the applicant.

## Submission conditions observed

The form requires Google sign-in; the inspected browser was not signed in. No CAPTCHA was observed before sign-in, and later steps remain unverified.

Google evaluates applications; submission does not grant access. The form limits requests to one per Cloud project and assigns quota per project. It describes the alpha as incomplete, for testing, without service or support guarantees. Submission includes agreement to Google's terms and participation in testing and feedback. The owner must review those commitments before the final submission.

No credentials, contact addresses, project IDs, completed form values, accepted terms, or submission confirmations are stored here.
