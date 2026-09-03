# Deploying SAMAN

Everything here is described in the main README under "Deploying to a link".
In short:

    cp .env.example .env            # then set SAMAN_SECRET_KEY and the domain
    make deploy-up                  # Caddy on :80/:443, the API behind it
    make deploy-up PROFILE=llm      # the same, with the local model beside the API
    make tunnel                     # a temporary public HTTPS link to :80, no account

The `../data` directory is mounted into the API container: the databases, the
learned model and any downloaded speech models live there and survive rebuilds.
