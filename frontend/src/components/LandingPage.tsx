import { Fragment, useEffect, useState, type ReactNode } from "react";
import type { AccountUser } from "../lib/api";
import { AccountNav } from "./AccountNav";

interface Props {
  themeToggle: ReactNode;
  backendReady: boolean;
  onUserChange: (user: AccountUser | null) => void;
}

type LandingView = "home" | "vision" | "about" | "research";

type Person = {
  name: string;
  title: string;
  affiliation: string;
  href?: string | null;
  img?: string | null;
  initials?: string;
};

const RESEARCH_TEAM: Person[] = [
  {
    name: "Dr. Rohini Srihari",
    title: "Principal Investigator",
    affiliation: "Professor · CSE",
    href: "https://engineering.buffalo.edu/computer-science-engineering/people/faculty-directory.host.html/content/shared/engineering/computer-science-engineering/profiles/faculty/ladder/srihari-rohini.detail.students.html",
    img: "/images/collaborators/rsrihari.jpg",
  },
  {
    name: "Sayantan Pal",
    title: "SPICA Research Lead",
    affiliation: "PhD Candidate · CSE",
    href: "https://sayantan-world.github.io/",
    img: "/images/collaborators/spal.jpg",
  },
  {
    name: "Akash Kolte",
    title: "Research Developer",
    affiliation: "MS · CSE",
    href: "https://akashkolte.us/",
    img: "/images/collaborators/akolte.jpg",
  },
];

const CODESIGN: Person[] = [
  {
    name: "Dr. Jeff Higginbotham",
    title: "AAC Research Collaborator",
    affiliation: "Professor · CADL",
    href: "https://ubwp.buffalo.edu/cadl/people-2/",
    img: "/images/collaborators/jhigginbotham.jpeg",
  },
  {
    name: "Jenna Bizovi",
    title: "AAC Research Collaborator",
    affiliation: "CADL",
    href: "https://ubwp.buffalo.edu/cadl/people-2/",
    img: "/images/collaborators/jbizovi.jpg",
  },
  {
    name: "Todd Hutchinson",
    title: "AAC Research Collaborator",
    affiliation: "CADL",
    href: "https://ubwp.buffalo.edu/cadl/people-2/",
    img: "/images/collaborators/thutchinson.png",
  },
];

const RESEARCH_THEMES = [
  "Personalized AAC",
  "Multimodal Interaction",
  "Memory & Agentic AI",
] as const;

const FEATURED_PUB = {
  year: "2026",
  venueShort: "IUI",
  title:
    "SPICA: Scalable and Personalized Conversational Agent Framework for AAC Users",
  blurb:
    "A scalable agentic framework for personalized AAC communication without model retraining.",
  authors: [
    "Sayantan Pal",
    "Nikhil Murali",
    "Atharva Vikas Jadhav",
    "Jenna Bizovi",
    "Antara Satchidanand",
    "Manohar Golleru",
    "Shalini Agarwal",
    "Todd Hutchinson",
    "Jeff Higginbotham",
    "Rohini K Srihari",
  ],
  venue:
    "Proceedings of the 31st International Conference on Intelligent User Interfaces (IUI '26), pp. 218-235",
  tags: ["Agentic AI", "Personalization", "AAC", "Memory"],
  href: "https://doi.org/10.1145/3742413.3789116",
  bibHref: "/cite/spica.bib",
};

const OTHER_PUBS = [
  {
    year: "2025",
    venueShort: "ATOB",
    title:
      "Developing Artificial Intelligence Applications for Human Conversation: Perspectives, Tools, Exploratory Analyses.",
    authors: [
      "Jeff Higginbotham",
      "Manohar Golleru",
      "Sayantan Pal",
      "Antara Satchidanand",
      "Jenna Bizovi",
      "Todd Hutchinson",
      "Michael Buckley",
      "Pamela Mathy",
      "Shalini Agarwal",
      "Rohini Srihari",
    ],
    venue: "Assistive Technology Outcomes & Benefits (ATOB), Vol. 19, p. 13",
    tags: ["Conversational AI", "AAC", "Human Conversation"],
    href: "https://www.atia.org/wp-content/uploads/2025/06/ATOB-V19_Final.pdf",
    bibHref: "/cite/atobv19_2025.bib",
  },
  {
    year: "2024",
    venueShort: "EMNLP CustomNLP4U",
    title:
      "Empowering AAC Users: A Systematic Integration of Personal Narratives with Conversational AI",
    authors: [
      "Sayantan Pal",
      "Souvik Das",
      "Rohini Srihari",
      "Jeff Higginbotham",
      "Jenna Bizovi",
    ],
    venue:
      "Proceedings of the 1st Workshop on Customizable NLP (CustomNLP4U) @ EMNLP 2024, pp. 12-25",
    tags: ["Personalization", "Conversational AI", "AAC"],
    href: "https://aclanthology.org/2024.customnlp4u-1.2/",
    bibHref: "/cite/emnlp_24.bib",
  },
] as const;

function AuthorsLine({ authors }: { authors: readonly string[] }) {
  return (
    <p className="pub-authors">
      {authors.map((name, i) => (
        <Fragment key={`${name}-${i}`}>
          {i > 0 ? " · " : null}
          {name === "Sayantan Pal" ? (
            <span className="pub-author-me">{name}</span>
          ) : (
            name
          )}
        </Fragment>
      ))}
    </p>
  );
}

function PersonCard({ person }: { person: Person }) {
  const body = (
    <>
      {person.img ? (
        <img src={person.img} alt="" className="profile-photo" />
      ) : (
        <span className="profile-photo profile-photo-fallback" aria-hidden="true">
          {person.initials || person.name.slice(0, 2)}
        </span>
      )}
      <span className="profile-copy">
        <span className="profile-name">{person.name}</span>
        <span className="profile-title">{person.title}</span>
        <span className="profile-role">{person.affiliation}</span>
      </span>
    </>
  );

  if (person.href) {
    return (
      <a
        className="profile-card"
        href={person.href}
        target="_blank"
        rel="noopener noreferrer"
      >
        {body}
      </a>
    );
  }

  return <div className="profile-card profile-card-static">{body}</div>;
}

function VisionPanel() {
  return (
    <section className="landing-panel landing-panel-vision" aria-label="Vision">
      <p className="landing-section-eyebrow">Vision</p>
      <h2 className="landing-section-title">Why we built SPICA</h2>
      <p className="landing-vision-lede">
        Communication should reflect the person, not just the words they can enter.
      </p>
      <div className="landing-prose landing-prose-narrow">
        <p>
          AAC users communicate in highly personal ways, through text, symbols, gestures,
          gaze, facial movements, air writing, and other individualized signals. Yet most
          AI-assisted AAC systems still treat communication primarily as text generation.
        </p>
      </div>

      <div className="approach-grid vision-pillars">
        <article className="approach-card">
          <h4>Personal</h4>
          <p>
            AAC communication is deeply individual. A useful system should understand the
            user’s style, preferences, memories, relationships, and lived experiences.
          </p>
        </article>
        <article className="approach-card">
          <h4>Multimodal</h4>
          <p>
            Communication extends beyond text. SPICA is designed to incorporate
            user-specific signals such as gestures, head and facial movements, air
            writing, and environmental context.
          </p>
        </article>
        <article className="approach-card">
          <h4>Private &amp; user-controlled</h4>
          <p>
            Personalization requires access to sensitive information. Users should remain
            in control of what the system observes, remembers, and uses to shape
            communication.
          </p>
        </article>
      </div>

      <div className="landing-vision-close">
        <h3>Our vision</h3>
        <p className="landing-vision-statement">
          SPICA aims to understand the person behind the interaction, combining multimodal
          communication, personal memory, and real-time reasoning to support communication
          that is efficient, authentic, private, and user-controlled.
        </p>
        <p className="landing-vision-traits">
          Personalized · Multimodal · Adaptive · Private
        </p>
        <p className="landing-vision-brandnote">
          SPICA, named after one of the brightest stars in the night sky.
        </p>
      </div>
    </section>
  );
}

function AboutPanel() {
  return (
    <section className="landing-panel landing-panel-wide" aria-label="About us">
      <p className="landing-section-eyebrow">About us</p>
      <h2 className="landing-section-title">About SPICA</h2>
      <p className="landing-about-headline">
        Building personalized AAC technology with the people who use it.
      </p>
      <div className="landing-prose landing-prose-narrow">
        <p>
          SPICA is a research initiative at the University at Buffalo exploring
          personalized, multimodal, and agentic AI for Augmentative and Alternative
          Communication.
        </p>
        <p>
          Our work brings together researchers in artificial intelligence, AAC experts,
          and AAC users to design communication systems that adapt to each person’s
          experiences, preferences, access needs, and ways of communicating.
        </p>
      </div>
      <p className="landing-affiliations">
        University at Buffalo · Computer Science &amp; Engineering · Communication and
        Assistive Device Laboratory
      </p>

      <h3 className="landing-subhead">Our approach</h3>
      <div className="approach-grid">
        <article className="approach-card">
          <h4>Personalized</h4>
          <p>
            Communication grounded in the user’s memories, preferences, identity, and
            communication style.
          </p>
        </article>
        <article className="approach-card">
          <h4>Multimodal</h4>
          <p>
            Supporting different ways of communicating, including text, AAC interfaces,
            gestures, gaze, and other user-specific signals.
          </p>
        </article>
        <article className="approach-card">
          <h4>Co-designed</h4>
          <p>
            Developed iteratively with AAC researchers, communication partners, and AAC
            users as active collaborators.
          </p>
        </article>
      </div>

      <h3 className="landing-subhead">Designed through collaboration</h3>
      <div className="landing-prose landing-prose-narrow">
        <p>
          AAC is inherently personal. There is no single interface, access method, or
          communication style that works for everyone. SPICA is therefore developed
          through an iterative collaboration between AI researchers, AAC researchers,
          communication partners, and people who rely on AAC themselves.
        </p>
        <p className="landing-emphasis">
          Our goal is not simply to build technology for AAC users, but to develop
          systems with them.
        </p>
      </div>

      <h3 className="landing-subhead">Research team</h3>
      <div className="profile-grid profile-grid-compact">
        {RESEARCH_TEAM.map((person) => (
          <PersonCard key={person.name} person={person} />
        ))}
      </div>

      <h3 className="landing-subhead">AAC research &amp; co-design collaborators</h3>
      <div className="profile-grid profile-grid-compact">
        {CODESIGN.map((person) => (
          <PersonCard key={person.name} person={person} />
        ))}
      </div>
    </section>
  );
}

function CiteDetails({ bibHref }: { bibHref: string }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!open || text !== null || error) return;
    let cancelled = false;
    fetch(bibHref)
      .then((r) => {
        if (!r.ok) throw new Error("Failed to load BibTeX");
        return r.text();
      })
      .then((body) => {
        if (!cancelled) setText(body.trim());
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, bibHref, text, error]);

  return (
    <div className="pub-cite">
      <button type="button" className="pub-cite-toggle" onClick={() => setOpen((v) => !v)}>
        {open ? "Hide citation" : "Cite"}
      </button>
      {open ? (
        <pre className="pub-cite-text">
          {error ? "Could not load BibTeX." : text ?? "Loading…"}
        </pre>
      ) : null}
    </div>
  );
}

function ResearchPanel() {
  return (
    <section className="landing-panel landing-panel-research" aria-label="Research">
      <p className="landing-section-eyebrow">Research</p>
      <h2 className="landing-section-title">Research, Publications &amp; Support</h2>
      <p className="landing-research-intro">
        SPICA brings together personalized AI, multimodal interaction, memory, and AAC
        to build communication systems that adapt to the individual.
      </p>

      <div className="research-theme-row" aria-label="Research themes">
        {RESEARCH_THEMES.map((theme) => (
          <span key={theme} className="research-theme-chip">
            {theme}
          </span>
        ))}
      </div>

      <h3 className="landing-subhead">Publications</h3>

      <article className="pub-featured">
        <div className="pub-meta">
          <span className="pub-badge">Featured</span>
          <span className="pub-venue-label">
            {FEATURED_PUB.year} · {FEATURED_PUB.venueShort}
          </span>
        </div>
        <h4 className="pub-title">{FEATURED_PUB.title}</h4>
        <p className="pub-blurb">{FEATURED_PUB.blurb}</p>
        <AuthorsLine authors={FEATURED_PUB.authors} />
        <p className="pub-venue">{FEATURED_PUB.venue}</p>
        <div className="pub-tags">
          {FEATURED_PUB.tags.map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <div className="pub-links">
          <a href={FEATURED_PUB.href} target="_blank" rel="noopener noreferrer">
            Read paper
          </a>
        </div>
        <CiteDetails bibHref={FEATURED_PUB.bibHref} />
      </article>

      <ul className="pub-compact-list">
        {OTHER_PUBS.map((pub) => (
          <li key={pub.title} className="pub-compact">
            <p className="pub-venue-label">
              {pub.year} · {pub.venueShort}
            </p>
            <h4 className="pub-title">{pub.title}</h4>
            <AuthorsLine authors={pub.authors} />
            <p className="pub-venue">{pub.venue}</p>
            <div className="pub-tags">
              {pub.tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
            <div className="pub-links">
              <a href={pub.href} target="_blank" rel="noopener noreferrer">
                Read paper
              </a>
            </div>
            <CiteDetails bibHref={pub.bibHref} />
          </li>
        ))}
      </ul>

      <h3 className="landing-subhead">Funding &amp; Support</h3>
      <article className="funding-card">
        <p className="pub-venue-label">Empire AI</p>
        <h4 className="pub-title">Empire AI Research Resources</h4>
        <p className="funding-focus">
          AI for people with motor neuron diseases and mental health needs
        </p>
        <p className="funding-body">
          Supporting research in personalized conversational AI and AAC technologies for
          people with ALS, cerebral palsy, and other motor neuron conditions.
        </p>
        <p className="funding-meta">
          <strong>Principal Investigator</strong>
          Rohini K. Srihari, University at Buffalo
        </p>
        <p className="funding-meta">
          <strong>Collaborators</strong>
          Jeffrey Higginbotham and researchers across Computer Science and Communicative
          Disorders &amp; Sciences
        </p>
        <div className="pub-links">
          <a
            href="https://www.buffalo.edu/news/releases/2025/03/empire-ai-projects-at-ub.html"
            target="_blank"
            rel="noopener noreferrer"
          >
            Learn more
          </a>
        </div>
      </article>
    </section>
  );
}

export function LandingPage({ themeToggle, backendReady, onUserChange }: Props) {
  const [view, setView] = useState<LandingView>("home");

  return (
    <div className={`landing-page${view === "home" ? " landing-home" : ""}`}>
      <div className="landing-wash" aria-hidden="true" />
      <header className="landing-top">
        <button
          type="button"
          className="landing-brand"
          onClick={() => setView("home")}
        >
          <img src="/favicon.svg" alt="" className="app-logo" />
          <span>SPICA</span>
        </button>
        <nav className="landing-nav" aria-label="Landing">
          <button
            type="button"
            className={view === "vision" ? "active" : undefined}
            onClick={() => setView("vision")}
          >
            Vision
          </button>
          <button
            type="button"
            className={view === "about" ? "active" : undefined}
            onClick={() => setView("about")}
          >
            About us
          </button>
          <button
            type="button"
            className={view === "research" ? "active" : undefined}
            onClick={() => setView("research")}
          >
            Research
          </button>
          {themeToggle}
        </nav>
      </header>

      <main className="landing-body">
        {view === "home" && (
          <div className="landing-split">
            <section className="landing-hero" aria-label="SPICA">
              <h1 className="landing-title">SPICA</h1>
              <p className="landing-highlight">
                Your voice. Your memories. Your way.
              </p>
              <p className="landing-lead">
                Personalized AAC conversations grounded in your experiences,
                preferences, and communication style.
              </p>
              <div className="landing-actions">
                <AccountNav onUserChange={onUserChange} variant="landing" />
              </div>
              {!backendReady && (
                <p className="landing-status">Connecting to the assistant…</p>
              )}
            </section>
            <aside className="landing-visual" aria-hidden="true">
              <img
                src="/images/teaser/setup.jpg"
                alt=""
                className="landing-teaser"
              />
            </aside>
          </div>
        )}

        {view === "vision" && <VisionPanel />}
        {view === "about" && <AboutPanel />}
        {view === "research" && <ResearchPanel />}
      </main>
    </div>
  );
}
