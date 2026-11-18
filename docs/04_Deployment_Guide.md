# AI Tuition Assistant — AWS Deployment Guide

This guide deploys the full stack to AWS, step by step in the AWS Console. The architecture and sizing are in [02_Technical_Design.md §11](02_Technical_Design.md#11-deployment-aws).

```
Internet ──80──▶ EC2 (Ubuntu 24.04, Elastic IP)
                 └─ docker compose (docker-compose.prod.yml)
                    Kong :80 ─▶ web · tuition-api · agent ─▶ mcp-server
                                      │
                                      └──5432 (TLS)──▶ RDS PostgreSQL 16 (private)
```

| Resource | Choice |
|---|---|
| Region | **Europe (Frankfurt) `eu-central-1`**. Any region works; use the same one for every resource. |
| EC2 | `t3.small` (2 vCPU, 2 GB), Ubuntu Server 24.04 LTS, 20 GB gp3 |
| RDS | PostgreSQL 16, `db.t4g.micro`, 20 GB gp2, single-AZ, no public access |
| Network | Default VPC. `tuition-ec2-sg` allows 80 from anywhere and 22 from your IP. `tuition-rds-sg` allows 5432 only from `tuition-ec2-sg`. |
| Cost | About $1/day while running (see [§9](#9-cost-and-teardown)) |

Console labels change from time to time. If a label below differs slightly, choose the option with the same meaning.

**Before you start**
- An AWS account with MFA on the root user, and a budget alert (AWS Budgets).
- A Gemini API key from Google AI Studio.
- A terminal with `ssh` (Windows 10/11 PowerShell includes OpenSSH).

---

## 1. Pick the region
1. Sign in to the AWS Console.
2. In the region menu at the top right, choose **Europe (Frankfurt) eu-central-1**.

## 2. Create the RDS database
1. Open **Aurora and RDS** (search "RDS") → **Databases** → **Create database**.
2. **Engine options**: **PostgreSQL**. The page may open with *Aurora (PostgreSQL Compatible)* and *Express configuration* selected; change both.
3. **Choose a database creation method**: **Full configuration** (called *Standard create* in older consoles), not *Easy create*. For **Engine version**, pick the latest **PostgreSQL 16.x** (the default is a newer major version). Leave **Enable RDS Extended Support** unticked.
4. **Templates**: **Free tier** (or *Sandbox*). This selects **Single-AZ DB instance deployment**.
5. **Settings**:
   - **DB instance identifier**: `tuition-db`
   - **Master username**: `tuition`
   - **Credentials management**: **Self managed**. *Managed in AWS Secrets Manager* costs extra and is not needed.
   - Leave **Auto generate password** unticked.
   - **Master password**: a strong password made of letters and digits only. Store it in your password manager; it is entered only on the server in [§7](#7-configure-and-start-the-stack).
6. **Instance configuration**: **Burstable classes** → `db.t4g.micro`.
7. **Storage**:
   - **Storage type**: General Purpose SSD (gp2 or gp3; both are in the free tier)
   - **Allocated storage**: `20` GiB
   - Open **Additional storage configuration** and untick **Enable storage autoscaling**.
8. **Connectivity**:
   - **Compute resource**: **Don't connect to an EC2 compute resource**. The instance does not exist yet; the firewall rule is added in [§5](#5-allow-the-server-to-reach-the-database).
   - **Virtual private cloud (VPC)**: the default VPC.
   - **DB subnet group**: the default.
   - **Public access**: **No**.
   - **VPC security group (firewall)**: **Create new**, name `tuition-rds-sg`.
   - **Availability Zone**: No preference.
   - **Database port** (under *Additional configuration*): `5432`.
9. **Database authentication**: **Password authentication**.
10. **Monitoring**: the free *Standard* option. Leave Performance Insights and Enhanced Monitoring off.
11. **Additional configuration** (near the bottom of the page):
    - **Initial database name**: `tuition`. Without it, RDS creates no database and the migrations fail.
    - **Backup retention period**: 1 day.
    - Untick **Enable deletion protection** so the database can be removed at the end.
12. Check **Estimated monthly costs** at the bottom, then click **Create database**. If a pop-up offers add-ons, close it.
13. Wait about 5–10 minutes until **Status** is *Available*.
14. Open `tuition-db` → **Connectivity & security** and copy the **Endpoint**, for example `tuition-db.abc123xyz.eu-central-1.rds.amazonaws.com`. It is called `<RDS_ENDPOINT>` below.

## 3. Create a key pair (SSH access)
1. Open **EC2** → left menu **Network & Security → Key Pairs** → **Create key pair**.
2. Fill in the form:
   - **Name**: `tuition-key`
   - **Key pair type**: RSA
   - **Private key file format**: `.pem`
3. Click **Create key pair**. The browser downloads `tuition-key.pem`.
4. Move the file to a safe folder, for example `C:\Users\<you>\.ssh\tuition-key.pem`. Do not put it in the repository.
5. Windows only: `ssh` refuses keys that other users can read, so restrict the file in PowerShell:
   ```powershell
   $key = "$env:USERPROFILE\.ssh\tuition-key.pem"
   icacls $key /inheritance:r
   icacls $key /grant:r "$($env:USERNAME):(R)"
   ```

## 4. Launch the EC2 instance
1. Open **EC2** → **Instances** → **Launch instances**.
2. **Name and tags**: `tuition-ec2`.
3. **Application and OS Images**: choose **Ubuntu**. The default image may be a newer release (26.04); open the **Amazon Machine Image (AMI)** list, pick **Ubuntu Server 24.04 LTS (HVM), SSD Volume Type**, and confirm the dialog that says some settings will be reset. Architecture: **64-bit (x86)**.
4. **Instance type**: `t3.small`.
5. **Key pair**: `tuition-key`.
6. **Network settings** → **Edit**:
   - **VPC**: the default VPC.
   - **Auto-assign public IP**: Enable.
   - **Firewall (security groups)**: **Create security group**.
     - **Name**: `tuition-ec2-sg`
     - **Description**: `Kong HTTP and admin SSH`
   - Inbound rule 1: **Type** SSH, **Source type** **My IP**.
   - **Add security group rule**: **Type** HTTP, **Source type** **Anywhere** (`0.0.0.0/0`).
   - Add no other rules. Ports 8000, 8100, 8200 and 5432 must stay closed. The smoke test checks this.
7. **Configure storage**: `20` GiB, **gp3**.
8. Click **Launch instance**, then **View all instances**. Wait until **Instance state** is *Running* and **Status check** shows *2/2 checks passed*.

### Attach an Elastic IP
A normal public IP changes when the instance stops. An Elastic IP stays the same, so the demo URL stays the same.
1. **EC2** → **Network & Security → Elastic IPs** → **Allocate Elastic IP address**.
2. Keep **Amazon's pool of IPv4 addresses** and click **Allocate**.
3. Select the new address, then **Actions → Associate Elastic IP address**:
   - **Resource type**: Instance
   - **Instance**: `tuition-ec2`
4. Click **Associate**.
5. Write the address down. It is called `<EIP>` below. The app will be served at `http://<EIP>/`.

## 5. Allow the server to reach the database
`tuition-rds-sg` must accept PostgreSQL traffic from the EC2 instance only.
1. **EC2** → **Network & Security → Security Groups** → select `tuition-rds-sg` → **Inbound rules** tab → **Edit inbound rules**.
2. Delete any existing rule. The console adds one for your own IP when the group is created; an IP rule cannot be switched to a security-group source, so delete it rather than editing it.
3. **Add rule**:
   - **Type**: PostgreSQL (port 5432 is filled in)
   - **Source**: Custom → start typing `tuition-ec2-sg` and pick it from the list.
4. **Description**: `Postgres from tuition-ec2`.
5. Click **Save rules**. The database is now reachable only from containers on `tuition-ec2`.

## 6. Connect to the server and install Docker
1. Connect from your computer:
   ```bash
   ssh -i ~/.ssh/tuition-key.pem ubuntu@<EIP>
   ```
   Answer `yes` to the host-key question the first time.
2. Clone the repository and install Docker. The `install` command adds Docker's official apt repository, Docker Engine and the compose plugin, plus a 2 GB swap file so the image builds fit in memory.
   ```bash
   git clone https://github.com/cancolak900/tuition-assistant.git
   cd tuition-assistant
   bash scripts/deploy.sh install
   ```
3. Log out (`exit`) and connect again, so your user can run `docker` without `sudo`.
4. Check that Docker works:
   ```bash
   docker compose version
   ```

## 7. Configure and start the stack
1. Write `.env`:
   ```bash
   cd ~/tuition-assistant
   bash scripts/deploy.sh env
   ```
2. Answer the prompts:
   - **RDS endpoint**: `<RDS_ENDPOINT>`
   - **Username** and **database name**: press Enter to keep the default `tuition`.
   - **Password** and **Gemini key**: typed hidden.

   The script then:
   - writes `.env` with mode 600,
   - percent-encodes the password,
   - adds `sslmode=require` (RDS for PostgreSQL 16 requires TLS),
   - generates a new random `JWT_SECRET`.

   `.env` stays on the server and is never committed.
3. Build, migrate, seed and start:
   ```bash
   bash scripts/deploy.sh up --seed
   ```
   The first build takes about 5–10 minutes on a `t3.small`. The script ends with `Up: http://<EIP>/`.
4. Check the containers:
   ```bash
   bash scripts/deploy.sh status
   ```
   All five services (kong, web, tuition-api, agent, mcp-server) should be *Up*, and the ones with health checks should be *(healthy)*.

## 8. Verify the deployment
Run these from your own computer, not from the server, so the checks go over the internet.

1. Smoke test of the gateway: health, login, JWT, rate limit, and closed backend ports.
   ```bash
   bash scripts/smoke.sh http://<EIP> | tee docs/evidence/smoke-aws.log
   ```
2. End-to-end agent scenarios A1–A6, with real Gemini:
   ```bash
   python scripts/scenarios.py --base-url http://<EIP> --yes | tee docs/evidence/scenarios-aws.log
   ```
3. In a browser:
   - Open `http://<EIP>/`.
   - Sign in as `s1001` / `Pass1001!` and ask "What is my balance?".
   - Sign in as `admin` / `Admin123!` and open the admin screen.
4. Swagger UI: `http://<EIP>/api/v1/docs`.
5. Screenshots to keep in `docs/evidence/`:
   - EC2 instance list (running, Elastic IP)
   - RDS database (Available, Public access *No*)
   - the EC2 security group inbound rules
   - the web app in the browser
6. Server logs, if anything fails:
   ```bash
   bash scripts/deploy.sh logs            # all services
   bash scripts/deploy.sh logs agent      # one service
   ```

### Day-to-day commands (on the server)

| Task | Command |
|---|---|
| Deploy the latest `main` | `bash scripts/deploy.sh update` |
| Fresh demo data, e.g. before recording | `bash scripts/deploy.sh reset-data` |
| Stop the containers | `bash scripts/deploy.sh down` |
| Rotate the Gemini key | edit `GEMINI_API_KEY` in `.env`, then `bash scripts/deploy.sh up` |

## 9. Cost and teardown
Approximate on-demand prices in `eu-central-1`:

| Item | Price |
|---|---|
| EC2 `t3.small` | ~$0.024/h |
| RDS `db.t4g.micro` | ~$0.018/h |
| Public IPv4 address | $0.005/h |
| Storage (2 × 20 GB SSD) | ~$0.15/day |
| **Total** | **about $1.2/day**, covered by free-plan credits |

**To pause** without losing data:
- Stop the EC2 instance and stop the RDS database.
- AWS starts a stopped RDS database again automatically after 7 days.
- The Elastic IP still costs $0.005/h while it is attached to a stopped instance.

**To remove everything** when the demo period ends, in this order:
1. **RDS** → `tuition-db` → **Actions → Delete**.
   - Untick *Create final snapshot*.
   - Tick the acknowledgement.
2. **EC2** → `tuition-ec2` → **Instance state → Terminate**.
3. **Elastic IPs** → select the address → **Actions → Release Elastic IP addresses**.
4. **Security groups**: delete `tuition-rds-sg`, then `tuition-ec2-sg`.
5. **Key pairs**: delete `tuition-key`.
6. Check **Billing → Bills** the next day to confirm no resources are left.

## 10. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `ssh` asks for a password, or says *permissions are too open* | Wrong user (it is `ubuntu`), or the key file is readable by others (see [§3](#3-create-a-key-pair-ssh-access) step 5). |
| `ssh` times out | Your IP changed. Edit `tuition-ec2-sg` → SSH rule → **My IP**. |
| `alembic upgrade` fails with *connection timed out* | `tuition-rds-sg` does not allow the instance. Check the inbound rule from [§5](#5-allow-the-server-to-reach-the-database): PostgreSQL, source `tuition-ec2-sg`. |
| *database "tuition" does not exist* | The initial database name was left empty. Create it once: `docker run --rm -it postgres:16-alpine psql "host=<RDS_ENDPOINT> user=tuition dbname=postgres sslmode=require" -c 'CREATE DATABASE tuition;'` |
| *no pg_hba.conf entry … no encryption* | `sslmode=require` is missing from `DATABASE_URL`. Run `bash scripts/deploy.sh env` again. |
| The build stops with *killed* or out of memory | Swap is missing. Run `bash scripts/deploy.sh install` again, then `up`. |
| The browser shows nothing on `http://<EIP>/` | Check the HTTP rule in `tuition-ec2-sg` and run `bash scripts/deploy.sh status`. |
| The agent replies with an LLM error | Check `GEMINI_API_KEY` in `.env`, and look for Gemini quota errors in `bash scripts/deploy.sh logs agent`. |
