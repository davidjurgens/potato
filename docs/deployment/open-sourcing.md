# Contributing to Potato

Potato is fully open-source and welcomes contributions from the community. This guide explains how to contribute effectively.

## Getting Started

### Prerequisites

- Python 3.8+
- Git
- A GitHub account

### Setting Up Your Development Environment

1. **Fork the repository** on GitHub

2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/potato.git
   cd potato
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-test.txt  # For running tests
   ```

4. **Run the tests** to ensure everything works:
   ```bash
   pytest
   ```

## Ways to Contribute

### Reporting Bugs

Found a bug? Please [open an issue](https://github.com/davidjurgens/potato/issues/new) with:
- A clear, descriptive title
- Steps to reproduce the problem
- Expected vs actual behavior
- Your environment (Python version, OS, browser if relevant)
- Error messages or logs if available

### Suggesting Features

Have an idea for improvement? [Open a feature request](https://github.com/davidjurgens/potato/issues/new) describing:
- The problem you're trying to solve
- Your proposed solution
- Why this would benefit other users

### Submitting Code

1. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**, following the [coding standards](#coding-standards)

3. **Write tests** for new functionality

4. **Run the test suite**:
   ```bash
   pytest tests/unit/ -v      # Fast unit tests
   pytest tests/server/ -v    # Integration tests
   ```

5. **Commit your changes** with a descriptive message:
   ```bash
   git commit -m "Add feature: brief description of changes"
   ```

6. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Open a Pull Request** on GitHub

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use meaningful variable and function names
- Add docstrings for public functions and classes
- Keep functions focused and reasonably sized

### Documentation

When adding or modifying features:

1. **Update relevant documentation** in the `docs/` directory
2. **Add or update example configurations** in `examples/`
3. **Include inline comments** for complex logic

See [Documentation Guidelines](#documentation-guidelines) for more details.

### Testing

- Write tests for new features and bug fixes
- Place unit tests in `tests/unit/`
- Place integration tests in `tests/server/`
- Ensure all tests pass before submitting a PR

## Documentation Guidelines

Every major feature should include:

1. **Administrator Documentation** (`docs/`):
   - Configuration options and defaults
   - YAML examples
   - Troubleshooting tips

2. **Example Project** (`examples/`):
   - Working configuration file
   - Sample data file
   - README if complex

### Documentation Style

- Use proper YAML syntax (not JSON-style)
- Include complete, runnable examples
- Cross-reference related documentation
- Add screenshots for UI features

## Pull Request Guidelines

### Before Submitting

- [ ] Tests pass locally (`pytest`)
- [ ] Code follows project style
- [ ] Documentation is updated
- [ ] Commit messages are clear
- [ ] Branch is up to date with main

### PR Description

Include:
- What the PR does
- Why the change is needed
- How to test the changes
- Screenshots for UI changes

## Development Roadmap

Current development priorities:

1. Enhanced UI/UX improvements
2. Additional annotation schema types
3. Better AI integration options
4. Performance optimizations
5. Documentation improvements

## Getting Help

- **Documentation**: [Potato Documentation](https://potato-annotation.readthedocs.io/)
- **Issues**: [GitHub Issues](https://github.com/davidjurgens/potato/issues)
- **Discussions**: [GitHub Discussions](https://github.com/davidjurgens/potato/discussions)

## Code of Conduct

Please be respectful and constructive in all interactions. We're all here to make Potato better.

## License

By contributing to Potato, you agree that your contributions will be licensed under the project's existing license.

---

Thank you for contributing to Potato!
