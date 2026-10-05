# How to use AI Agent for Academic

## Opening the app

1. Double-click **Start AI Agent.command** in this folder.
   - The very first time, a black window installs the app. This takes a few minutes and happens once.
   - If the Mac says the file "cannot be opened", right-click it, choose **Open**, then **Open** again.
2. Your web browser opens the app. **Keep the black window open while you work.** Closing it stops the app.

## One-time setting: your API key

1. In the app, open **⚙️ Settings** in the left sidebar.
2. Paste your Anthropic API key (from console.anthropic.com → API keys) and press **Save settings**.
3. Optional: add your email for PubMed, and a free Semantic Scholar key (it avoids "too many requests" errors).

## A literature review

1. Open the **📚 Literature Review** tab, choose **New review**, type your question, and press **Create review**.
   - Choose **Step by step** to check each stage, or **All 5 steps automatically**.
2. Check the **protocol** (criteria and search strings). You can edit it.
3. After **screening**, look at the papers marked **Maybe** and set each one to *include* or *exclude*.
   You can override any decision. Press **Save screening decisions**; the PRISMA counts update by themselves.
4. Check the **evidence table** and correct any cell. Press **Save**, then **Re-write the review**.
5. Download the review as **Word**, the evidence table as **CSV**, and the references as **BibTeX/RIS**
   for EndNote, Zotero or Mendeley.

## A manuscript

1. At the end of a review, press **Use these papers in the Writing Agent**. Then open the
   **✍️ Academic Writing** tab: the reference list is already filled in.
2. Add your study notes and results: type them, paste them, or upload a Word or PDF file.
   - Already have a finished paper? Choose **A finished manuscript** to get the peer review,
     response letter and revision only.
3. Press **Create project**. You get:
   the manuscript draft → the top 5 journals → 3 simulated reviewers → a response letter → a revised
   manuscript with every change in **bold**.
4. Edit the manuscript in the **✏️ Edit** tab whenever you like. Later steps are then marked ⚠️, so you
   can re-run them.

## Where your files are

Everything is saved automatically in the **Outputs** folder inside this folder (Word and Markdown copies):

- `Outputs/Literature reviews/<your question>/`
- `Outputs/Manuscripts/<your project>/`

The **📁 My files** tab lists them all, and **Open the Outputs folder** opens the folder in Finder.

## Important

- Everything the app writes is a **draft**. Check every citation, number and claim before you use it.
- Missing facts appear as **[TO BE ADDED BY AUTHORS]**. Fill these in yourself.
- Do **not** enter patient names, IC numbers or other identifiable patient information.
- Do not share the hidden `.env` file: it contains your API key.
