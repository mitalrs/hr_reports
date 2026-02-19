### hr reports

control on reports

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app hr_reports
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/hr_reports
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit


test cases added for 
- Column presence/order                                                       
- Status logic (Present/Half Day/Absent)                                      
- Shift detection
- Overtime calculation
- Date format validation
- In/Out time sanity
- Working hours calculation
- employee col validator
- blank shift cell on absent status

