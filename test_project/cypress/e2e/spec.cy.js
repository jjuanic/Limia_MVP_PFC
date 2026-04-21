describe('Register Account', () => {
  it('should register a new account with valid credentials', () => {
    cy.visit('/')

    // Click on the register button
    cy.get('#register-link').click()

    // Fill in the registration form fields
    cy.get('#name').type('John Doe')
    cy.get('#email').type('john@example.com')
    cy.get('#password').type('password123')

    // Click on the create account button
    cy.get('#register-btn').contains('Create Account').click()

    // Verify that a green advice appears
    cy.contains('.visible', 'Your account has been created!')

    // Wait for 5 seconds before checking the route path
    cy.wait(5000)

    // Verify that we are redirected to the correct route path
    cy.url().should('contain', '/login')
  })
})