from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def create_resume_pdf(filename: str, name: str, summary: str, skills: list, experience: list, education: list):
    path = Path(__file__).parent / filename
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter

    y = height - 50

    # Header
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, y, name)
    y -= 25

    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Email: {name.lower().replace(' ', '.')}@example.com | Phone: +1 555-0199 | Location: San Francisco, CA")
    y -= 30

    # Summary
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "PROFESSIONAL SUMMARY")
    y -= 15
    c.setFont("Helvetica", 10)
    c.drawString(50, y, summary[:100])
    y -= 15
    if len(summary) > 100:
        c.drawString(50, y, summary[100:200])
        y -= 25
    else:
        y -= 15

    # Skills
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "TECHNICAL SKILLS")
    y -= 15
    c.setFont("Helvetica", 10)
    c.drawString(50, y, " • " + ", ".join(skills))
    y -= 30

    # Experience
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "WORK EXPERIENCE")
    y -= 20
    for exp in experience:
        c.setFont("Helvetica-Bold", 11)
        c.drawString(50, y, f"{exp['title']} - {exp['company']} ({exp['duration']})")
        y -= 15
        c.setFont("Helvetica", 10)
        for bullet in exp['bullets']:
            c.drawString(60, y, f"• {bullet}")
            y -= 15
        y -= 10

    # Education
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "EDUCATION")
    y -= 20
    for edu in education:
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"• {edu['degree']} - {edu['institution']} ({edu['year']})")
        y -= 15

    c.save()
    print(f"Created {filename}")

if __name__ == "__main__":
    # Candidate 1: Senior Backend Engineer (Alex Chen) - Strong Match for Backend Role
    create_resume_pdf(
        filename="sample_candidate_alex.pdf",
        name="Alex Chen",
        summary="Senior Backend Engineer with 5+ years of experience designing scalable distributed microservices, REST APIs, and event-driven data streaming architectures.",
        skills=["Python", "FastAPI", "Flask", "PostgreSQL", "MySQL", "Redis", "Kafka", "Kubernetes", "Docker", "AWS", "CI/CD", "Linux", "Git"],
        experience=[
            {
                "title": "Senior Backend Developer",
                "company": "CloudScale Systems",
                "duration": "2021 - Present (3 years)",
                "bullets": [
                    "Engineered high-throughput REST APIs and event-driven pipelines using Python FastAPI and Apache Kafka.",
                    "Deployed containerized microservices to Kubernetes clusters on AWS EKS with automated CI/CD pipelines.",
                    "Optimized PostgreSQL queries and implemented Redis caching, lowering latency by 55%."
                ]
            },
            {
                "title": "Backend Software Engineer",
                "company": "Nexus Tech",
                "duration": "2019 - 2021 (2 years)",
                "bullets": [
                    "Developed core RESTful backend services using Python and Flask integrated with MySQL.",
                    "Managed Docker containerization and automated deployments using GitHub Actions."
                ]
            }
        ],
        education=[
            {
                "degree": "Bachelor of Science in Computer Science",
                "institution": "University of Washington",
                "year": "2019"
            }
        ]
    )

    # Candidate 2: Junior Frontend Developer (Jordan Taylor) - Weak Match for Backend Role
    create_resume_pdf(
        filename="sample_candidate_jordan.pdf",
        name="Jordan Taylor",
        summary="Frontend Web Developer focused on responsive UI design, accessible client-side components, and interactive single-page applications.",
        skills=["HTML5", "CSS3", "JavaScript", "TypeScript", "React", "Vue.js", "TailwindCSS", "Figma", "Git"],
        experience=[
            {
                "title": "Junior Frontend Developer",
                "company": "Creative Pixel Studio",
                "duration": "2023 - Present (1 year)",
                "bullets": [
                    "Built responsive web user interfaces using React, TypeScript, and TailwindCSS.",
                    "Collaborated with UI/UX designers to translate Figma wireframes into pixel-perfect pages.",
                    "Optimized client-side web assets, improving Lighthouse performance score to 95+."
                ]
            }
        ],
        education=[
            {
                "degree": "Bachelor of Arts in Graphic Design & Web Interaction",
                "institution": "State Arts University",
                "year": "2023"
            }
        ]
    )
