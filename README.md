# wb-dab-report

Posts WeBuddhist app analytics from PostHog to the team's Discord channel, written for people without an analytics background. Once they're set up, the reports also show installs by channel (Airbridge), crash-free users and notification delivery (Firebase) and website visits (Microsoft Clarity): see [Other sources](#other-sources-airbridge-firebase-clarity).

| Report  | When (IST)                | Cron (UTC)    | Covers                                   | Compared with                  |
|---------|---------------------------|---------------|------------------------------------------|--------------------------------|
| Daily   | Every day, 9:00 AM        | `30 3 * * *`  | Yesterday                                | The day before, and the 7 days before |
| Weekly  | Mondays, 9:15 AM          | `45 3 * * 1`  | The Monday to Sunday that just ended     | The week before                |
| Monthly | 1st of the month, 9:30 AM | `0 4 1 * *`   | The calendar month that just ended       | The month before               |

GitHub runs cron in UTC and sometimes starts scheduled runs a few minutes late. Days are UTC days, the PostHog project's timezone, so a day runs from 5:30 AM to 5:30 AM IST and matches the PostHog dashboard.

The weekly and monthly reports attach three PNG charts drawn on the runner with matplotlib. No data goes to an outside chart service. If Discord refuses the images, the report is posted without them.

## Secrets

Set under **Settings > Secrets and variables > Actions**:

- `POSTHOG_API_KEY`: PostHog personal API key with query access to project 449016.
- `DISCORD_WEBHOOK_URL`: the team channel. Scheduled runs post here.
- `DISCORD_TEST_WEBHOOK_URL`: a test channel. Manual runs post here and fail if it isn't set.

The other sources add two more secrets and some variables, listed below.

## Other sources: Airbridge, Firebase, Clarity

Each source is optional and appears in its own section under the PostHog figures once its settings are in place. If a source fails on a given day, the report still posts, with one line saying that source's figures couldn't be fetched, and the Actions log gets a warning (without numbers).

Secrets go under **Settings > Secrets and variables > Actions > Secrets**, variables under the **Variables** tab on the same page.

| Source | Reports | What it shows | Settings |
|---|---|---|---|
| Airbridge | All | Installs and the top channels they came from | Secret `AIRBRIDGE_API_TOKEN`; variables `AIRBRIDGE_APP`, `AIRBRIDGE_TIMEZONE` |
| Firebase Crashlytics | All | Crash-free users, per platform | Variables `FIREBASE_PROJECT_ID`, `BIGQUERY_LOCATION`, plus the Google Cloud sign-in below |
| Firebase Cloud Messaging | All | Share of notifications that reached Android phones | Variables `FIREBASE_PROJECT_ID`, `FIREBASE_ANDROID_APP_ID`, plus the Google Cloud sign-in below |
| Microsoft Clarity | Daily only | Website visits, pages and time per visit, rage clicks, dead clicks, page errors | Secret `CLARITY_API_TOKEN` |

### Airbridge

1. In Airbridge, open **Settings > Tokens** and copy the **API Token** (not the Tracking Link API Token). The token carries the permissions of the person who made it, so use an Owner or In-house Marketer account; Agency accounts don't see organic installs.
2. Save it as the secret `AIRBRIDGE_API_TOKEN`.
3. Set the variable `AIRBRIDGE_APP` to the app name shown in **Settings > Tokens**, and `AIRBRIDGE_TIMEZONE` to the app timezone shown in **Settings > App Settings**, written like `Asia/Kolkata`.

Airbridge counts days in the app's timezone, not UTC, so its day runs slightly differently from the PostHog figures. It also corrects the previous two days at 9 PM UTC, so the latest day can still rise a little.

### Microsoft Clarity

In Clarity, open the website project's **Settings > Data Export > Generate new API token** (project admins only), and save the token as the secret `CLARITY_API_TOKEN`.

Clarity's API covers only the 24 hours before the call and allows 10 calls a day per project, so its figures appear in the daily report only, and manual runs use up the same allowance.

### Firebase

**In Firebase** (needs an Owner or Firebase Admin):

1. Move the project to the Blaze plan if it isn't on it. The free BigQuery sandbox deletes data after 60 days and may not support the current Crashlytics export.
2. Open **Project settings > Integrations > BigQuery**, link the project, turn on **Crashlytics**, and tick **Include sessions** (without sessions there's nothing to count crash-free users against). Note the dataset location you choose, for example `US` or `asia-south1`. The first export can take up to 48 hours.
3. Copy the Android app's **App ID** from **Project settings > General > Your apps** (it looks like `1:123456789:android:abc123`).

**In Google Cloud**, give this repository a read-only service account it signs in to without a key. Run these in [Cloud Shell](https://shell.cloud.google.com) for the Firebase project:

```sh
PROJECT_ID=your-firebase-project-id
LOCATION=US                      # the BigQuery dataset location from step 2
REPO_ID=1399693297               # Webuddhist-tech/wb-dab-report
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
SA="wb-dab-report@$PROJECT_ID.iam.gserviceaccount.com"

gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  cloudresourcemanager.googleapis.com bigquery.googleapis.com fcmdata.googleapis.com --project "$PROJECT_ID"

gcloud iam service-accounts create wb-dab-report --project "$PROJECT_ID" \
  --display-name "Discord reports (read-only)"

# Only this repository's main branch can sign in, matched by its numeric ID so a renamed or reused name can't
gcloud iam workload-identity-pools create github --project "$PROJECT_ID" --location global \
  --display-name "GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc wb-dab-report --project "$PROJECT_ID" \
  --location global --workload-identity-pool github \
  --issuer-uri "https://token.actions.githubusercontent.com" \
  --attribute-mapping "google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref" \
  --attribute-condition "assertion.repository_id == '$REPO_ID' && assertion.ref == 'refs/heads/main'"
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT_ID" \
  --role roles/iam.workloadIdentityUser \
  --member "principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository_id/$REPO_ID"

# Read-only access: run queries, read the two Firebase datasets, read notification delivery data
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role roles/bigquery.jobUser
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA" --role roles/firebasecloudmessaging.viewer
for DATASET in firebase_crashlytics firebase_sessions; do
  bq query --project_id "$PROJECT_ID" --location "$LOCATION" --use_legacy_sql=false \
    "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`$PROJECT_ID.$DATASET\` TO \"serviceAccount:$SA\""
done

echo "GCP_WORKLOAD_IDENTITY_PROVIDER = projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/wb-dab-report"
echo "GCP_SERVICE_ACCOUNT            = $SA"
```

Then set these variables: `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_SERVICE_ACCOUNT` (the two lines printed at the end), `FIREBASE_PROJECT_ID`, `BIGQUERY_LOCATION`, and `FIREBASE_ANDROID_APP_ID`. If only one platform is exported to BigQuery, also set `CRASHLYTICS_PLATFORMS` to `ANDROID` or `IOS`. Sign-in changes can take 5 minutes to work.

The crash tables are read as `org_pecha_app_ANDROID` and `org_pecha_app_IOS` (from `APP_NAMESPACE` in `wbreport/config.py`). Queries are capped at 2 GB each.

## Run a report by hand

Open **Actions**, pick *Daily report*, *Weekly report* or *Monthly report*, and click **Run workflow**. Leave the date empty for the latest complete day, week or month, or enter any date (`YYYY-MM-DD`) inside the period you want. Manual runs always post to the test channel. A date inside a week or month that isn't over yet gives a preview up to yesterday.

On your own machine (Python 3.11 or newer):

```sh
pip install -r requirements.txt
export POSTHOG_API_KEY=...            # never commit this
python -m wbreport weekly --date 2026-10-01 --dry-run out/   # writes out/weekly.json and the charts
python -m wbreport daily --target test                       # needs DISCORD_TEST_WEBHOOK_URL
```

To include the other sources locally, export the same secrets and variables. For Firebase, `GOOGLE_ACCESS_TOKEN=$(gcloud auth print-access-token)` works if your own Google account can read the datasets. With a date picked, Airbridge and Crashlytics report on that date, Firebase notifications only if it's within the week Firebase keeps, and Clarity is left out.

## How the numbers are counted

All figures are counts of people or medians across people, computed inside PostHog (or the other source). No names, IDs or per-person rows leave those services. The repository is public, so the script never prints the numbers in the Actions log.

| In the report | Counted as |
|---|---|
| People who opened the app | Unique people with at least one screen view in the mobile app |
| New | People whose first screen view ever falls in the period |
| Came back | Of last week's (or month's) new people, the share who opened the app again in this one |
| Time on screen | Each person's time with the app on screen that day: within each app session, the time from one event to the next, leaving out stretches in the background (from the app going to the background until it opens again). The report shows the middle person (half had it on screen longer, half shorter), the share under a minute and the share at half an hour or more. Times are rounded to what people can picture (45 sec, 4½ min, 12 min), and changes are given in minutes from those rounded figures |
| Read a text, joined a live session, opened a plan | Unique people who opened the reader, entered a live group session, or opened a plan |
| Phones | Each person counted once, under the platform they used most |
| Main reading language | Each reader counted once, under the language they read in most |
| From install to first practice | People who installed in the period, followed in order within 24 hours: signed in or chose guest, finished the welcome setup, then read, joined a live session, opened a plan day, or started the mala or timer |
| Installs, came from | Airbridge's app installs, by channel, in the app's timezone. "Organic" means no ad or tracking link. Meta's privacy rules round some of its counts down |
| Crash-free | Of the app installations that opened the app (Firebase sessions), the share that had no crash closing the app. Firebase exports this once a day at no fixed time, so the daily report shows the day before yesterday, and a week or month stops there too |
| Notifications reached | Firebase's share of notifications delivered to Android phones that share usage data with Google, weighted across all messages. It runs up to 5 days behind and has no iPhone figures. Weekly and monthly reports show the latest days Firebase has |
| Website visits | Clarity's visits in the 24 hours before the report ran, without bot visits. Pages and active time are averages per visit; problems are the share of visits with at least one |

The daily "What changed" line is written by fixed rules in `wbreport/text.py`: how many days in a row the number moved, whether one platform carried the change, and which signal (notification opens, live-session joins, first-time people) moved with it.

Tracking went live on 25 Sep 2026 (`TRACKING_START` in `wbreport/config.py`). A comparison period that starts before that date shows its totals side by side and compares per-day figures only.

## Keeping the schedules running

GitHub turns off scheduled workflows in a public repository after 60 days without a commit, and emails the admins first. If that happens, re-enable each workflow from the Actions tab.
