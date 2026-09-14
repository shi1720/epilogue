# Submission checklist — for Shivam

Everything is built. Here is the shortest path from this repo to a submitted entry.
Total hands-on time: ~60–90 minutes, most of it the video.

## 1. Repository (5 min)

- [ ] The working branch `claude/quirky-knuth-4o6pqv` is already the repo's **default branch**, so everything is live as-is. *(Optional tidy-up: Settings → Branches → rename it to `main`; GitHub updates the default automatically.)*
- [ ] Make the repository **public** (Settings → General → Danger Zone → Change visibility).
- [ ] Confirm GitHub shows **"MIT license"** in the About sidebar (it auto-detects `LICENSE`; give it a minute after going public).
- [ ] Set the About description: *"Epilogue — the agent that settles what's left behind. Autonomous after-loss administration on Strands Agents + Amazon Bedrock."* Add topics: `strands-agents`, `aws`, `bedrock`, `ai-agents`, `hackathon`.
- [ ] *(Optional but nice)* Rename the repo to `epilogue` (Settings → General). GitHub redirects the old URL automatically; if you do this, use the new URL everywhere below.

## 2. Model credentials for the demo (5 min)

Pick ONE:

- **Bedrock (best for judging optics + the $50 AWS credits):** in the AWS console, enable model access for *Anthropic Claude Sonnet* in `us-east-1` (Bedrock → Model access), create an access key, then:
  `export AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_REGION=us-east-1`
  If your account uses a different Claude model id, also set `EPILOGUE_MODEL_ID` (check Bedrock → Model catalog for the exact inference-profile id).
- **Anthropic API (fastest):** `pip install -e ".[anthropic]"`, then
  `export EPILOGUE_MODEL_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-…`

Sanity check before recording: `epilogue demo`, open the dashboard, click **Use the demo case → Begin**, and confirm the live feed starts moving within ~30s.

## 3. The video (45–60 min)

- [ ] Open `docs/VIDEO_SCRIPT.md` — the voiceover is written **word for word** (~4:25 at a calm pace) with screen directions and a shot checklist.
- [ ] Slides are at `docs/media/slides.pptx` (speaker notes included). Slides 1–3 open, 4–6 close.
- [ ] Do one rehearsal run, reset (`epilogue reset` or delete `data/`), then record the take.
- [ ] Upload to YouTube (public or unlisted — both are accepted).

## 4. Devpost form (15 min)

- [ ] `docs/DEVPOST.md` is a copy-paste kit: name, tagline, track (**Everyday Agents**), full story, built-with tags, and testing instructions for judges.
- [ ] Attach: video URL, public repo URL, and screenshots from `docs/media/`.
- [ ] You'll need your **AWS Builder ID** (create at profile.aws.amazon.com if you don't have one).

## 5. Bonus points (15 min)

- [ ] Publish `docs/BLOG_POST.md` on **builder.aws.com** *before the deadline*. The required "Agents for Humans" phrase is already in the title. Add 2–3 screenshots from `docs/media/`.

## 6. Optional polish (if time remains)

- [ ] **Live demo link** (projects with one score higher): the fastest path is AWS App Runner straight from the Dockerfile — push the image to ECR (`docker build -f deploy/Dockerfile -t epilogue . && aws ecr …`), create an App Runner service (0.25 vCPU is plenty), set the AWS credentials/region env vars, and paste the service URL into Devpost. Your $50 AWS credits cover this for weeks. (Add HTTP basic auth or note it's a shared demo — one case at a time.)
- [ ] Deploy to AgentCore (`deploy/agentcore/`) and mention the live deployment in the Devpost text — it strengthens Technical Implementation.
- [ ] Add the demo video as a link at the top of the README.

## Deadline

**Sep 15, 2026, 5:30 AM IST** (Sep 15, 00:00 UTC). Submit at least 30 minutes early — Devpost forms get slow near deadlines.
