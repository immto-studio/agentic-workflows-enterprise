# Agentic Workflows in the Large Enterprise: companion code

Code, Terraform, and lab instructions for the book *Agentic Workflows in the Large Enterprise*
(Enterprise Agent Platforms, book 1) by Mykhailo Krasniuk.

Corrections to the book are listed in [ERRATA.md](ERRATA.md), and the pages behind its product facts in
[LINKS.md](LINKS.md).

## Layout

```
docs/          which chapter uses which lab, the rules every lab follows, and the book's decisions the labs cite
labs/          one folder for each chapter that has a lab of its own, each with its README, results, and teardown
terraform/     the billing alarms, one configuration for each cloud (the chapters' own Terraform sits in their labs)
workflows/     the five Larkspur Mutual workflows, W1 to W5, each with its servers, golden set, and kept runs
```

[docs/chapter-lab-map.md](docs/chapter-lab-map.md) says which chapter uses which folder, and
[docs/lab-safety.md](docs/lab-safety.md) gives the rules every lab follows on spending, teardown, identity, and data.

## Reading the references

The labs were built alongside the book, and their READMEs and code keep the references of that work:

- **W1-D5, E-D6, O-D7.** A numbered decision of a lab's plan: W1 to W5 are the workflows, E is chapter 15's lab, and O is chapter 16's. Each of those folders lists its plan's decisions in its DECISIONS.md.
- **D-029.** One of the book's own decisions, summarized in [docs/book-decisions.md](docs/book-decisions.md).
- **The fact sheet, section 8.8, or LINKS.md, chapter 16, section 8.8.** The notes the book's facts were collected in. [LINKS.md](LINKS.md) gives the addresses of their pages, under each sheet's own headings.
- **ch03:58.** A line of the book's manuscript, which isn't published; read it as chapter 3.
- **fig-16-01, lst-04-03, tbl-14-01.** The book's figure 16.1, listing 4.3, and table 14.1.
- **#104, companion #10, book #26.** An issue or a pull request of the book's planning, which stayed private. Companion issues #8 to #14 were the plans of W1 to W5 and of chapters 15 and 16, and their decisions are in the DECISIONS.md files.

All scenarios are set at Larkspur Mutual, a fictional insurer. Any resemblance to a real company is accidental.
